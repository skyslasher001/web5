import httpx
import pytest

from tests.support.fake_ollama import CHAT_MODEL, FakeOllama
from universe_agents.providers import OpenAICompatibleProvider, ProviderError
from universe_agents.router import ModelRouter, NoModelAvailable
from universe_common.egress import EgressGate
from universe_models.ollama import OllamaClient


def _router(url: str, *, assignment: str | None = None, override: str | None = None, prefs: list[str] | None = None):
    client = OllamaClient(url, EgressGate(), cache_s=0)
    return ModelRouter(client, assignment=lambda _t: assignment, override=override, preferences=lambda _t: prefs or [])


async def test_capabilities_are_looked_up_once_per_model_version(fake_ollama: FakeOllama) -> None:
    client = OllamaClient(fake_ollama.url, EgressGate(), cache_s=0)
    models = await client.list_models(refresh=True)
    for _ in range(2):
        models = await client.list_models(refresh=True)
    assert {m.name: m.capabilities for m in models} == {
        "fake-chat:latest": ["completion", "tools"],  # the stand-in model can call tools, like qwen3
        "fake-embed:latest": ["embedding"],
    }
    assert fake_ollama.show_requests == 2  # not 6: cached by (name, digest)
    await client.aclose()


async def test_capabilities_listed_in_tags_need_no_show_calls(fake_ollama: FakeOllama) -> None:
    fake_ollama.capabilities_in_tags = True
    client = OllamaClient(fake_ollama.url, EgressGate(), cache_s=0)
    models = await client.list_models(refresh=True)
    assert models[0].capabilities == ["completion", "tools"]
    assert fake_ollama.show_requests == 0
    await client.aclose()


async def test_router_falls_back_to_any_installed_chat_model(fake_ollama: FakeOllama) -> None:
    assert await _router(fake_ollama.url).resolve("local-fast") == CHAT_MODEL


async def test_agents_with_tools_need_a_tool_capable_model(fake_ollama: FakeOllama) -> None:
    assert await _router(fake_ollama.url).resolve("local-fast", needs_tools=True) == CHAT_MODEL
    fake_ollama.chat_tools = False
    router = _router(fake_ollama.url)
    assert await router.resolve("local-fast") == CHAT_MODEL  # plain chat still works
    with pytest.raises(NoModelAvailable) as caught:
        await router.resolve("local-fast", needs_tools=True)
    assert "can call tools" in str(caught.value) and caught.value.hint.startswith("Run: ollama pull")


async def test_router_prefers_assignment_then_preferences(fake_ollama: FakeOllama) -> None:
    assert await _router(fake_ollama.url, assignment=CHAT_MODEL).resolve("local-fast") == CHAT_MODEL
    assert await _router(fake_ollama.url, prefs=["gemma4:e4b", "fake-chat"]).resolve("local-fast") == "fake-chat"


async def test_router_never_picks_embedding_models(fake_ollama: FakeOllama) -> None:
    fake_ollama.with_models = True
    result = await _router(fake_ollama.url).resolve("local-fast")
    assert result != "fake-embed:latest"


async def test_router_explains_missing_models() -> None:
    empty = FakeOllama(with_models=False).start()
    try:
        with pytest.raises(NoModelAvailable) as info:
            await _router(empty.url, prefs=["gemma4:e4b"]).resolve("local-fast")
        assert info.value.hint == "Run: ollama pull gemma4:e4b"
        with pytest.raises(NoModelAvailable, match="not installed"):
            await _router(empty.url, override="qwen3.8:27b").resolve("local-fast")
    finally:
        empty.stop()


async def test_router_reports_unreachable_ollama() -> None:
    with pytest.raises(NoModelAvailable, match="not reachable"):
        await _router("http://127.0.0.1:9").resolve("local-fast")


async def test_provider_streams_deltas(fake_ollama: FakeOllama) -> None:
    http = EgressGate().async_client(purpose="chat", local_only=True, base_url=fake_ollama.url)
    provider = OpenAICompatibleProvider(http)
    messages = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hello world"}]
    deltas = [d async for d in provider.stream(CHAT_MODEL, messages, max_tokens=64)]  # type: ignore[arg-type]
    assert "".join(deltas).strip() == "Echo from the fake model: hello world"
    assert fake_ollama.chat_requests[-1]["stream"] is True
    await provider.aclose()


async def test_provider_turns_server_errors_into_provider_errors(fake_ollama: FakeOllama) -> None:
    http = EgressGate().async_client(purpose="chat", local_only=True, base_url=fake_ollama.url)
    provider = OpenAICompatibleProvider(http)
    with pytest.raises(ProviderError, match="500"):
        async for _ in provider.stream(CHAT_MODEL, [{"role": "user", "content": "[[fail]]"}], max_tokens=8):
            pass
    dead = OpenAICompatibleProvider(
        EgressGate().async_client(purpose="chat", local_only=True, base_url="http://127.0.0.1:9")
    )
    with pytest.raises(ProviderError, match="cannot reach"):
        async for _ in dead.stream(CHAT_MODEL, [{"role": "user", "content": "x"}], max_tokens=8):
            pass
    await provider.aclose()
    await dead.aclose()


def test_httpx_is_the_transport() -> None:
    # The provider must use the gate's client (and therefore its checks), not its own.
    assert isinstance(EgressGate().async_client(purpose="x", local_only=True), httpx.AsyncClient)


TOOLS = [{"type": "function", "function": {"name": "vault__search", "description": "", "parameters": {}}}]


async def test_tool_calls_are_assembled_from_streamed_fragments(fake_ollama: FakeOllama) -> None:
    provider = OpenAICompatibleProvider(httpx.AsyncClient(base_url=fake_ollama.url))
    seen: list[str] = []
    turn = await provider.complete(
        CHAT_MODEL, [{"role": "user", "content": "[[loop]]"}], tools=TOOLS, max_tokens=64, on_token=seen.append
    )
    [call] = turn.tool_calls
    assert call.name == "vault__search" and call.arguments == {"query": "same thing"} and call.error is None
    assert call.id.startswith("call_") and turn.finish_reason == "tool_calls"
    assert turn.tokens_in == 50 and turn.tokens_out >= 10  # from the usage chunk
    assert seen == []  # no text in this turn

    bad = await provider.complete(CHAT_MODEL, [{"role": "user", "content": "[[bad-args]]"}], tools=TOOLS, max_tokens=64)
    assert bad.tool_calls[0].error is not None and bad.tool_calls[0].raw_arguments == "{not json"

    text = await provider.complete(CHAT_MODEL, [{"role": "user", "content": "hello"}], tools=TOOLS, max_tokens=64)
    assert text.tool_calls == [] and text.content.strip() == "Echo from the fake model: hello"
    await provider.aclose()
