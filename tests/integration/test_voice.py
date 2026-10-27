"""Voice through Core (Phase 7, ADR-0016): Core starts the real voice process (with stand-in engines: CI can't
download the models), hands out single-use tickets, the renderer's WebSocket speaks and listens, settings and
per-agent voices persist, the kill switch stops voice, memos land in the vault and get transcribed, and model
installs are gated, hash-checked and requeue transcription."""

import asyncio
import hashlib
import io
import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import InvalidStatus
from websockets.sync.client import connect

from tests.conftest import AUTH, REPO
from tests.integration.test_vault_api import BASE, Api
from tests.support.fake_ollama import FakeOllama
from tests.support.fake_voice import FakeSTT, utterances
from universe_core.app import create_app
from universe_core.context import CoreContext
from universe_core.settings import CoreSettings
from universe_vault import store
from universe_vault.transcription import NO_STT, Transcriber
from universe_voice import models
from universe_voice.audio import STT_RATE, float_to_pcm16, write_wav
from universe_voice.vad import EnergyVAD

WS = BASE.replace("http://", "ws://")


def ctx_of(api: Api) -> CoreContext:
    return api.client.app.state.ctx  # type: ignore[attr-defined]


@pytest.fixture
def api(make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama) -> Iterator[Api]:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as client:
        a = Api(client, settings, fake_ollama.url)
        manager = ctx_of(a).require_voice().manager
        manager.command = [sys.executable, "-m", "tests.support.fake_voice_server"]
        manager.env = {**manager.env, "PYTHONPATH": str(REPO), "UNIVERSE_FAKE_STT_LINES": "take me to Ember Wolf"}
        yield a
        a.close()


def put(api: Api, path: str, body: Any) -> Any:
    response = api.client.put(f"/api/v1{path}", json=body, headers=AUTH)
    assert response.status_code == 200, response.text
    return response.json()


def test_voice_is_off_until_you_turn_it_on(api: Api) -> None:
    status = api.get("/voice/status")
    assert status["state"] == "off" and status["pid"] is None
    assert {m["id"] for m in status["models"]} == {"whisper-tiny.en", "whisper-base.en", "kokoro-82m", "silero-vad"}
    assert not any(m["installed"] for m in status["models"])
    assert status["settings"]["mode"] == "push_to_talk" and status["settings"]["wake_phrase"] == "hey universe"
    ticket = api.post("/session/ws-ticket")["ticket"]
    with pytest.raises(WebSocketDisconnect) as closed, api.client.websocket_connect(f"{WS}/ws/voice?ticket={ticket}"):
        pass
    assert closed.value.code == 4503  # nothing to talk to


def test_start_speak_listen_and_stop_through_core(api: Api) -> None:
    status = api.post("/voice/start")
    assert status["state"] == "ready", status["reason"]
    assert status["tts"] == "fake-kokoro" and status["stt"] == "fake-whisper" and status["pid"]
    ticket = api.post("/session/ws-ticket")["ticket"]

    with api.client.websocket_connect(f"{WS}/ws/voice?ticket={ticket}") as ws:
        ready = ws.receive_json()
        assert ready["type"] == "ready" and "am_michael" in ready["voices"]
        # Speak: a header, then the PCM, per sentence; then the end marker.
        ws.send_json({"type": "speak", "text": "Flying to Ember Wolf. It has twelve items.", "id": "s1"})
        got: list[Any] = []
        while not (got and isinstance(got[-1], dict) and got[-1].get("type") == "speech_end"):
            message = ws.receive()
            got.append(json.loads(message["text"]) if message.get("text") is not None else message["bytes"])
        headers = [m for m in got if isinstance(m, dict) and m["type"] == "audio"]
        assert [h["seq"] for h in headers] == [0, 1] and all(h["rate"] == 24000 for h in headers)
        assert sum(isinstance(m, bytes) for m in got) == 2
        assert got[-1] == {"type": "speech_end", "id": "s1", "chunks": 2, "cancelled": False}
        # Listen (push-to-talk): hold, talk, release → the transcript.
        ws.send_json({"type": "push", "down": True})
        ws.send_bytes(float_to_pcm16(utterances(("speech", 1.0))))
        ws.send_json({"type": "push", "down": False})
        assert _until(ws, "final")["text"] == "take me to Ember Wolf"

    # A ticket works once.
    with pytest.raises(WebSocketDisconnect) as closed, api.client.websocket_connect(f"{WS}/ws/voice?ticket={ticket}"):
        pass
    assert closed.value.code == 4401
    # The voice process only answers Core: without Core's HMAC ticket it refuses the handshake.
    port = ctx_of(api).require_voice().manager.port
    with pytest.raises(InvalidStatus) as refused:
        connect(f"ws://127.0.0.1:{port}/ws?ticket=forged.ticket")
    assert refused.value.response.status_code == 403

    pid = status["pid"]
    status = api.post("/voice/stop")
    assert status["state"] == "off" and status["pid"] is None
    assert not _alive(pid)
    actions = [r["action"] for r in api.get("/audit", params={"limit": 50})]
    assert "voice.started" in actions and "voice.stopped" in actions


def _until(ws: Any, kind: str) -> dict[str, Any]:
    for _ in range(200):
        message = ws.receive()
        if message.get("text") is not None and (event := json.loads(message["text"]))["type"] == kind:
            return event
    raise AssertionError(f"no {kind} event")


def _alive(pid: int) -> bool:
    import psutil

    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def test_settings_persist_and_agents_have_their_own_voices(api: Api) -> None:
    status = put(api, "/voice/settings", {"wake_phrase": "Hey  Universe ", "mode": "wake", "speed": 1.2})
    assert status["settings"]["wake_phrase"] == "hey universe" and status["settings"]["mode"] == "wake"
    assert api.get("/voice/status")["settings"]["speed"] == 1.2
    voices = {a["agent_id"]: a["voice"] for a in api.get("/voices")["agents"]}
    assert voices["core"] == "af_heart" and voices["navigator"] == "af_nova" and voices["critic"] == "bm_george"
    assert len(set(voices.values())) == len(voices)  # every agent sounds different
    put(api, "/voice/settings", {"agents": {"navigator": "bf_isabella"}})
    assert {a["agent_id"]: a["voice"] for a in api.get("/voices")["agents"]}["navigator"] == "bf_isabella"
    response = api.client.put("/api/v1/voice/settings", json={"stt": "whisper-huge"}, headers=AUTH)
    assert response.status_code == 400


def test_kill_switch_stops_voice_and_keeps_it_off(api: Api) -> None:
    if ctx_of(api).safety is None:
        pytest.skip("needs the Phase 3 protected-core patch (kill switch)")
    assert api.post("/voice/start")["state"] == "ready"
    api.post("/killswitch", {"engaged": True})
    deadline = time.monotonic() + 10
    while api.get("/voice/status")["state"] != "off" and time.monotonic() < deadline:
        time.sleep(0.05)
    status = api.get("/voice/status")
    assert status["state"] == "off" and status["reason"] == "kill switch engaged"
    api.post("/voice/start", expect=409)


def test_a_voice_memo_is_saved_and_transcribed(api: Api, tmp_path: Path) -> None:
    buf = io.BytesIO()
    path = tmp_path / "memo.wav"
    write_wav(path, utterances(("pause", 0.5), ("speech", 1.2), ("pause", 0.8)), STT_RATE)
    buf.write(path.read_bytes())
    response = api.client.post(
        "/api/v1/voice/memo",
        params={"title": "Bridge idea"},
        content=buf.getvalue(),
        headers={**AUTH, "Content-Type": "audio/wav"},
    )
    assert response.status_code == 201, response.text
    item_id = response.json()["item_id"]
    item = api.get(f"/items/{item_id}")
    assert item["type"] == "voice_memo" and item["title"] == "Bridge idea"
    assert not list((api.vault.cache / "uploads").iterdir())  # the staged upload is gone

    stt = FakeSTT(["the bridge goes up a key"])
    api._ctx.transcriber = Transcriber(tmp_path, engines=lambda: (stt, EnergyVAD()))
    api.drain()
    hits = api.get("/search", params={"q": "bridge key", "mode": "keyword"})["hits"]
    assert [h["item"]["id"] for h in hits] == [item_id]

    bad = api.client.post("/api/v1/voice/memo", content=b"not audio", headers={**AUTH, "Content-Type": "audio/wav"})
    assert bad.status_code == 400
    wrong = api.client.post("/api/v1/voice/memo", content=b"x", headers={**AUTH, "Content-Type": "text/plain"})
    assert wrong.status_code == 415


# ---------- installs ----------


class Files(BaseHTTPRequestHandler):
    files: ClassVar[dict[str, bytes]] = {}
    hits: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        self.hits.append(self.path)
        if self.path.startswith("/redirect/"):
            self.send_response(302)
            self.send_header("Location", self.path.removeprefix("/redirect"))
            self.end_headers()
            return
        body = self.files.get(self.path)
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


@pytest.fixture
def files_server() -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Files)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def _model(base: str, body: bytes, *, sha: str | None = None, kind: models.Kind = "stt") -> models.VoiceModel:
    download = models.Download(f"{base}/redirect/m.onnx", sha or hashlib.sha256(body).hexdigest(), len(body))
    return models.VoiceModel("whisper-test", kind, "test", "MIT", "local", (download,), ("m.onnx",))


def _run(api: Api, coro: Any) -> Any:
    return api.client.portal.call(lambda: coro)  # type: ignore[union-attr]


def test_install_follows_redirects_checks_the_hash_and_requeues_transcription(
    api: Api, files_server: str, tmp_path: Path
) -> None:
    ctx = ctx_of(api)
    voice = ctx.require_voice()
    # An audio item that was skipped because no Whisper was installed.
    wav = tmp_path / "inbox.wav"
    write_wav(wav, utterances(("speech", 1.0)), STT_RATE)
    api.post("/ingest/paths", {"paths": [str(wav)]}, 202)
    api._ctx.transcriber = Transcriber(voice.models_dir)
    api.drain()
    [item] = api.get("/items")["items"]
    stages = {s.stage: s for s in store.stages(api._ctx.conn, item["id"])}
    assert stages["transcribe"].detail == NO_STT

    body = b"onnx-bytes" * 1000
    Files.files = {"/m.onnx": body}
    tampered = _model(files_server, body, sha="0" * 64)

    async def install(model: models.VoiceModel) -> None:
        voice.installer.start(model)
        await voice.installer.wait(model.id)

    _run(api, install(tampered))
    state = voice.installer.installs["whisper-test"]
    assert state.state == "failed" and "pinned SHA-256" in (state.error or "")
    assert not (voice.models_dir / "whisper-test").exists() or not any((voice.models_dir / "whisper-test").iterdir())

    good = _model(files_server, body)
    _run(api, install(good))
    assert voice.installer.installs["whisper-test"].state == "done"
    assert (voice.models_dir / "whisper-test" / "m.onnx").read_bytes() == body
    assert not list((voice.models_dir / ".downloads").iterdir())
    assert "/redirect/m.onnx" in Files.hits and "/m.onnx" in Files.hits
    # The STT install requeued the skipped item.
    stages = {s.stage: s for s in store.stages(api._ctx.conn, item["id"])}
    assert stages["transcribe"].status == "pending"
    events = [e["type"] for e in api.get("/events", params={"tail": 200})["events"]]
    assert "voice.model.installed" in events and "voice.model.failed" in events


def test_installs_are_refused_offline(make_settings: Callable[..., CoreSettings]) -> None:
    with TestClient(create_app(make_settings(offline=True)), base_url=BASE) as client:
        response = client.post("/api/v1/voice/models/whisper-tiny.en/install", headers=AUTH)
        assert response.status_code == 409 and "offline" in response.text
        missing = client.post("/api/v1/voice/models/nope/install", headers=AUTH)
        assert missing.status_code == 404


def test_the_gate_blocks_model_downloads_when_offline(api: Api, files_server: str) -> None:
    """Even past the API check, the download itself goes through the gate (remote URL + offline → denied)."""
    voice = ctx_of(api).require_voice()
    ctx_of(api).gate.offline = True
    model = models.VoiceModel(
        "whisper-remote",
        "stt",
        "t",
        "MIT",
        "x",
        (models.Download("https://github.com/example/m.onnx", "0" * 64, 10),),
        ("m.onnx",),
    )

    async def install() -> None:
        voice.installer.start(model)
        await voice.installer.wait(model.id)

    _run(api, install())
    state = voice.installer.installs["whisper-remote"]
    assert state.state == "failed" and "offline" in (state.error or "").lower()


# ---------- review 2026-10-21: regressions ----------


def test_stop_wins_over_a_start_queued_behind_a_respawn(api: Api) -> None:
    """The kill switch's stop() used to lose to a start() waiting on the lock: the start made a new monitor
    and voice came back after the kill switch."""
    manager = ctx_of(api).require_voice().manager
    config = ctx_of(api).require_voice().config()

    async def scenario() -> tuple[str, bool]:
        await manager.start(config)
        crashed = manager._proc
        assert crashed is not None
        crashed.kill()  # the voice process dies...
        await asyncio.to_thread(crashed.wait)
        async with manager._lock:
            starter = asyncio.create_task(manager.start(config))
            stopper = asyncio.create_task(manager.stop(reason="kill switch engaged"))
            await asyncio.sleep(0.05)
        await asyncio.gather(starter, stopper)
        await asyncio.sleep(2.5)  # a stray monitor would have respawned by now
        proc = manager._proc
        return manager.state, proc is not None and proc.poll() is None

    state, alive = api.client.portal.call(scenario)  # type: ignore[union-attr]
    assert state == "off" and not alive


def test_the_audio_relay_never_goes_through_a_proxy(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """websockets uses the system proxy by default; the mic stream must stay on loopback."""
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.delenv(name, raising=False)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # nothing listens there
    assert api.post("/voice/start")["state"] == "ready"
    ticket = api.post("/session/ws-ticket")["ticket"]
    with api.client.websocket_connect(f"{WS}/ws/voice?ticket={ticket}") as ws:
        assert ws.receive_json()["type"] == "ready"
