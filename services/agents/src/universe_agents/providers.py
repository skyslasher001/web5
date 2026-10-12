"""Chat providers behind one OpenAI-compatible interface (SPEC §15).

A thin streaming client over the egress-gated httpx client: POST /v1/chat/completions with
stream=true and parse the server-sent events. Works with Ollama, llama.cpp server and any
OpenAI-compatible endpoint.
"""

import json
from collections.abc import AsyncIterator
from typing import Literal, Protocol, TypedDict

import httpx


class ChatMessage(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: str


class ProviderError(RuntimeError):
    """The model server failed or returned something we can't use. Message is user-presentable."""


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
