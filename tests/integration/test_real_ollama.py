"""The model path against a *real* Ollama server, with a tiny generated model (nothing is downloaded).

Starts a throwaway `ollama serve` on a free port with its own model store, registers the GGUF from
tests/support/tiny_gguf.py (a chat model and an embedding model), then checks the client, router, streaming
provider, a full Core chat, and the vault pipeline embedding a note plus hybrid search over it.
Skipped when no `ollama` binary is available; point UNIVERSE_TEST_OLLAMA at one to run it anywhere.
"""

import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from universe_vault.layout import Vault
from universe_vault.worker import build_context, drain

from tests.conftest import AUTH, free_port
from tests.support.tiny_gguf import write_tiny_llama
from universe_agents.providers import OpenAICompatibleProvider, ProviderError
from universe_agents.router import ModelRouter
from universe_common.egress import EgressGate
from universe_core.app import create_app
from universe_core.settings import CoreSettings
from universe_models.ollama import OllamaClient

OLLAMA = os.environ.get("UNIVERSE_TEST_OLLAMA") or shutil.which("ollama")
MODEL = "universe-tiny:latest"
EMBED_MODEL = "universe-tiny-embed:latest"
MODELFILE = 'FROM ./tiny.gguf\nTEMPLATE """{{ range .Messages }}{{ .Content }}\n{{ end }}"""\n'

pytestmark = [pytest.mark.slow, pytest.mark.skipif(not OLLAMA, reason="no ollama binary (set UNIVERSE_TEST_OLLAMA)")]


@pytest.fixture(scope="module")
def real_ollama(tmp_path_factory: pytest.TempPathFactory) -> Iterator[str]:
    assert OLLAMA
    home = tmp_path_factory.mktemp("ollama")
    port = free_port()
    env = {
        **os.environ,
        "HOME": str(home),
        "OLLAMA_HOST": f"127.0.0.1:{port}",
        "OLLAMA_MODELS": str(home / "models"),
    }
    log = (home / "serve.log").open("wb")
    server = subprocess.Popen([OLLAMA, "serve"], env=env, stdout=log, stderr=subprocess.STDOUT)
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if httpx.get(f"{url}/api/version", timeout=1).status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if server.poll() is not None or time.monotonic() > deadline:
                raise RuntimeError(f"ollama serve did not start:\n{(home / 'serve.log').read_text()[-2000:]}")
            time.sleep(0.2)
        write_tiny_llama(home / "tiny.gguf")
        (home / "Modelfile").write_text(MODELFILE, encoding="utf-8")
        created = subprocess.run(
            [OLLAMA, "create", MODEL, "-f", "Modelfile"],
            cwd=home,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert created.returncode == 0, created.stdout + created.stderr
        write_tiny_llama(home / "embed.gguf", embedding=True)
        (home / "Modelfile.embed").write_text("FROM ./embed.gguf\n", encoding="utf-8")
        created = subprocess.run(
            [OLLAMA, "create", EMBED_MODEL, "-f", "Modelfile.embed"],
            cwd=home,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert created.returncode == 0, created.stdout + created.stderr
        yield url
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()
        log.close()


async def test_client_reads_the_real_model_list_and_capabilities(real_ollama: str) -> None:
    client = OllamaClient(real_ollama, EgressGate())
    try:
        status = await client.status()
        assert status.reachable and status.version
        models = {m.name: m for m in await client.list_models(refresh=True)}
        assert MODEL in models
        assert "completion" in models[MODEL].capabilities
        assert models[MODEL].family == "llama"
        assert models[MODEL].size_bytes
    finally:
        await client.aclose()


async def test_router_picks_the_installed_model(real_ollama: str) -> None:
    client = OllamaClient(real_ollama, EgressGate(), cache_s=0)
    try:
        router = ModelRouter(client, assignment=lambda _t: None, override=None, preferences=lambda _t: [])
        assert await router.resolve("local-fast") == MODEL
    finally:
        await client.aclose()


async def test_provider_streams_real_tokens(real_ollama: str) -> None:
    provider = OpenAICompatibleProvider(
        EgressGate().async_client(purpose="ollama", local_only=True, base_url=real_ollama)
    )
    try:
        chunks = [
            c
            async for c in provider.stream(MODEL, [{"role": "user", "content": "hello"}], max_tokens=8, temperature=0.0)
        ]
        assert chunks, "the real server streamed no tokens"
        assert all(isinstance(c, str) and c for c in chunks)
    finally:
        await provider.aclose()


async def test_provider_reports_an_unknown_model_clearly(real_ollama: str) -> None:
    provider = OpenAICompatibleProvider(
        EgressGate().async_client(purpose="ollama", local_only=True, base_url=real_ollama)
    )
    try:
        with pytest.raises(ProviderError, match="404"):
            async for _ in provider.stream("no-such-model:latest", [{"role": "user", "content": "hi"}], max_tokens=4):
                pass
    finally:
        await provider.aclose()


def test_core_chat_end_to_end_with_a_real_model(real_ollama: str, make_settings: Callable[..., CoreSettings]) -> None:
    settings = make_settings(ollama_url=real_ollama)
    with TestClient(create_app(settings), base_url=f"http://127.0.0.1:{settings.port}") as client:
        info = client.get("/api/v1/models", headers=AUTH).json()
        assert info["ollama"]["reachable"] is True and info["chat_model"] == MODEL
        sent = client.post("/api/v1/chat", json={"text": "hello universe"}, headers=AUTH)
        assert sent.status_code == 202, sent.text
        conversation_id = sent.json()["conversation_id"]
        deadline = time.monotonic() + 60
        while True:
            messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=AUTH).json()
            if len(messages) == 2:  # the reply is stored once the stream ends
                break
            assert time.monotonic() < deadline, messages
            time.sleep(0.1)
        reply = messages[1]
        assert reply["status"] == "complete", reply
        assert reply["model"] == MODEL
        assert reply["content"]
        assert reply["first_token_ms"] is not None


def test_vault_embeds_with_a_real_embedding_model(
    real_ollama: str, make_settings: Callable[..., CoreSettings], tmp_path: Path
) -> None:
    settings = make_settings(ollama_url=real_ollama)
    with TestClient(create_app(settings), base_url=f"http://127.0.0.1:{settings.port}") as client:
        created = client.post("/api/v1/capture", json={"text": "Heron sightings at the pond"}, headers=AUTH)
        assert created.status_code == 201, created.text
        item_id = created.json()["item_id"]
        ctx = build_context(Vault(settings.vault_dir), worker_id="real", ollama_url=real_ollama)
        try:
            drain(ctx)
        finally:
            if ctx.ollama:
                ctx.ollama.close()
            ctx.conn.close()
        item = client.get(f"/api/v1/items/{item_id}", headers=AUTH).json()
        embed = next(s for s in item["stages"] if s["stage"] == "embed")
        assert embed["status"] == "done" and embed["model"] == EMBED_MODEL, embed
        assert json.loads(embed["detail"])["dim"] == 64
        result = client.get("/api/v1/search", params={"q": "heron pond"}, headers=AUTH).json()
        assert result["mode"] == "hybrid" and result["semantic"] is True
        assert result["hits"][0]["item"]["id"] == item_id
