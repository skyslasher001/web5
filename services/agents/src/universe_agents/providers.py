"""Chat providers behind one OpenAI-compatible interface (SPEC §15).

A thin streaming client over the egress-gated httpx client: POST /v1/chat/completions with
stream=true and parse the server-sent events. Works with Ollama, llama.cpp server and any
OpenAI-compatible endpoint.
"""

import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypedDict

import httpx


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ProviderError(RuntimeError):
    """The model server failed or returned something we can't use. Message is user-presentable."""


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    raw_arguments: str  # as the model sent it; kept so a malformed call can be shown back to it
    error: str | None = None  # set when the arguments weren't a JSON object


@dataclass
class Turn:
    """One model response: text, tool calls, or both."""

    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    finish_reason: str | None = None


def _parse_arguments(raw: str | dict[str, Any] | None) -> tuple[dict[str, Any], str, str | None]:
    if isinstance(raw, dict):  # some servers send an object instead of a JSON string
        return raw, json.dumps(raw), None
    text = raw or "{}"
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return {}, text, f"arguments are not valid JSON: {exc.msg}"
    if not isinstance(value, dict):
        return {}, text, "arguments must be a JSON object"
    return value, text, None


class ChatProvider(Protocol):
    def stream(
        self, model: str, messages: list[ChatMessage], *, max_tokens: int, temperature: float
    ) -> AsyncIterator[str]: ...


class OpenAICompatibleProvider:
    def __init__(self, http: httpx.AsyncClient, *, api_key: str | None = None) -> None:
        # `http` must come from EgressGate.async_client with base_url set to the server root.
        self._http = http
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}

    async def aclose(self) -> None:
        await self._http.aclose()

    async def stream(
        self, model: str, messages: list[ChatMessage], *, max_tokens: int, temperature: float = 0.7
    ) -> AsyncIterator[str]:
        body = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        timeout = httpx.Timeout(connect=5.0, read=120.0, write=10.0, pool=5.0)
        try:
            async with self._http.stream(
                "POST", "/v1/chat/completions", json=body, headers=self._headers, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    raise ProviderError(f"model server returned {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        return
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"model server sent malformed data: {data[:200]}") from exc
                    if "error" in chunk:
                        raise ProviderError(f"model server error: {chunk['error']}")
                    for choice in chunk.get("choices", []):
                        delta = (choice.get("delta") or {}).get("content")
                        if delta:
                            yield delta
        except httpx.ConnectError as exc:
            raise ProviderError(f"cannot reach the model server at {self._http.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("the model server timed out") from exc

    async def complete(
        self,
        model: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int,
        temperature: float = 0.3,
        on_token: Callable[[str], None] | None = None,
    ) -> Turn:
        """One streamed completion that may call tools (OpenAI tool-calling format).

        Text deltas go to `on_token` as they arrive; tool-call fragments are assembled by index.
        """
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "stream_options": {"include_usage": True},
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if tools:
            body["tools"] = tools
        timeout = httpx.Timeout(connect=5.0, read=180.0, write=10.0, pool=5.0)
        turn = Turn()
        text: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        try:
            async with self._http.stream(
                "POST", "/v1/chat/completions", json=body, headers=self._headers, timeout=timeout
            ) as response:
                if response.status_code >= 400:
                    detail = (await response.aread()).decode("utf-8", errors="replace")[:500]
                    raise ProviderError(f"model server returned {response.status_code}: {detail}")
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError as exc:
                        raise ProviderError(f"model server sent malformed data: {data[:200]}") from exc
                    if "error" in chunk:
                        raise ProviderError(f"model server error: {chunk['error']}")
                    usage = chunk.get("usage") or {}
                    turn.tokens_in = usage.get("prompt_tokens", turn.tokens_in) or turn.tokens_in
                    turn.tokens_out = usage.get("completion_tokens", turn.tokens_out) or turn.tokens_out
                    for choice in chunk.get("choices", []):
                        delta = choice.get("delta") or choice.get("message") or {}
                        if delta.get("content"):
                            text.append(delta["content"])
                            if on_token is not None:
                                on_token(delta["content"])
                        for fragment in delta.get("tool_calls") or []:
                            slot = calls.setdefault(fragment.get("index", len(calls)), {"args": []})
                            if fragment.get("id"):
                                slot["id"] = fragment["id"]
                            function = fragment.get("function") or {}
                            if function.get("name"):
                                slot["name"] = function["name"]
                            arguments = function.get("arguments")
                            if isinstance(arguments, dict):
                                slot["args"] = [json.dumps(arguments)]
                            elif arguments:
                                slot["args"].append(arguments)
                        if choice.get("finish_reason"):
                            turn.finish_reason = choice["finish_reason"]
        except httpx.ConnectError as exc:
            raise ProviderError(f"cannot reach the model server at {self._http.base_url}") from exc
        except httpx.TimeoutException as exc:
            raise ProviderError("the model server timed out") from exc
        turn.content = "".join(text)
        for index in sorted(calls):
            slot = calls[index]
            if not slot.get("name"):
                continue
            arguments, raw, error = _parse_arguments("".join(slot["args"]))
            turn.tool_calls.append(ToolCall(slot.get("id") or f"call_{index}", slot["name"], arguments, raw, error))
        if not turn.tokens_out:  # servers that don't report usage: a rough estimate keeps limits meaningful
            turn.tokens_out = max(1, len(turn.content) // 4) if turn.content or turn.tool_calls else 0
        return turn
