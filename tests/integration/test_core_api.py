"""Core API through the real ASGI app and a real (fake) Ollama over HTTP."""

import time
from collections.abc import Callable
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import AUTH, TOKEN
from tests.support.fake_ollama import FakeOllama
from universe_core.app import create_app
from universe_core.settings import CoreSettings

BASE = "http://127.0.0.1:47999"
WS = "ws://127.0.0.1:47999/ws"


def _ticket(client: TestClient) -> str:
    return client.post("/api/v1/session/ws-ticket", headers=AUTH).json()["ticket"]


def _wait_for(client: TestClient, predicate: Callable[[list[dict[str, Any]]], bool], timeout: float = 5.0) -> list:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = client.get("/api/v1/events", headers=AUTH).json()["events"]
        if predicate(events):
            return events
        time.sleep(0.02)
    raise AssertionError("condition not met in time")


def test_health_is_public_but_everything_else_needs_the_token(client: TestClient) -> None:
    assert client.get("/api/v1/health").json()["status"] == "ok"
    assert client.get("/api/v1/projects").status_code == 401
    assert client.get("/api/v1/projects", headers={"Authorization": "Bearer wrong"}).status_code == 401
    assert client.get("/api/v1/projects", headers=AUTH).status_code == 200


def test_dns_rebinding_and_foreign_origins_are_refused(client: TestClient) -> None:
    assert client.get("/api/v1/health", headers={"Host": "evil.example:47999"}).status_code == 403
    assert client.get("/api/v1/health", headers={"Origin": "https://evil.example"}).status_code == 403
    preflight = client.options(
        "/api/v1/projects",
        headers={
            "Origin": "app://universe",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "authorization",
        },
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == "app://universe"


def test_seed_galaxies_exist_once(make_settings: Callable[..., CoreSettings]) -> None:
    settings = make_settings()
    names: list[str] = []
    for _ in range(2):  # second boot must not duplicate
        with TestClient(create_app(settings), base_url=BASE) as c:
            names = [p["name"] for p in c.get("/api/v1/projects", headers=AUTH).json()]
    assert names == ["Ember Wolf Acquisitions", "DevMind", "Algo trading bot", "UNIVERSE"]


def test_chat_streams_over_websocket_and_is_stored(client: TestClient) -> None:
    with client.websocket_connect(f"{WS}?ticket={_ticket(client)}") as ws:
        ws.send_json({"op": "chat.send", "text": "plan my week", "id": "r1"})
        tokens: list[str] = []
        seen: list[str] = []
        conversation_id = None
        while True:
            msg = ws.receive_json()
            if msg["kind"] == "ack":
                assert msg["ok"] and msg["id"] == "r1"
                conversation_id = msg["result"]["conversation_id"]
                continue
            event = msg["event"]
            seen.append(event["type"])
            if event["type"] == "chat.token":
                tokens.append(event["payload"]["delta"])
            if event["type"] == "agent.completed":
                break
    assert "".join(tokens).strip() == "Echo from the fake model: plan my week"
    assert seen.index("agent.started") < seen.index("chat.started") < seen.index("chat.token")
    messages = client.get(f"/api/v1/conversations/{conversation_id}/messages", headers=AUTH).json()
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["status"] == "complete" and messages[1]["model"] == "fake-chat:latest"
    assert messages[1]["first_token_ms"] is not None


def test_clients_can_name_a_new_conversation(client: TestClient) -> None:
    import uuid

    cid = str(uuid.uuid4())
    sent = client.post("/api/v1/chat", json={"text": "hi", "conversation_id": cid}, headers=AUTH)
    assert sent.status_code == 202 and sent.json()["conversation_id"] == cid
    bad = client.post("/api/v1/chat", json={"text": "hi", "conversation_id": "not-a-uuid"}, headers=AUTH)
    assert bad.status_code == 400


def test_tail_returns_the_newest_events(client: TestClient) -> None:
    for i in range(3):
        client.post("/api/v1/errors", json={"service": "desktop", "kind": f"E{i}", "message": "m"}, headers=AUTH)
    events = client.get("/api/v1/events?tail=2", headers=AUTH).json()["events"]
    assert [e["payload"]["kind"] for e in events] == ["E1", "E2"]


def test_ws_tickets_are_single_use(client: TestClient) -> None:
    ticket = _ticket(client)
    with client.websocket_connect(f"{WS}?ticket={ticket}") as ws:
        ws.send_json({"op": "ping"})
        assert ws.receive_json()["kind"] == "pong"
    try:
        with client.websocket_connect(f"{WS}?ticket={ticket}") as ws:
            ws.receive_json()
        raise AssertionError("reused ticket was accepted")
    except Exception as exc:  # starlette raises WebSocketDisconnect with code 4401
        assert getattr(exc, "code", None) == 4401


def test_history_is_sent_to_the_model(client: TestClient, fake_ollama: FakeOllama) -> None:
    first = client.post("/api/v1/chat", json={"text": "my name is Sam"}, headers=AUTH).json()
    _wait_for(client, lambda ev: any(e["type"] == "agent.completed" for e in ev))
    client.post(
        "/api/v1/chat", json={"text": "what is my name?", "conversation_id": first["conversation_id"]}, headers=AUTH
    )
    _wait_for(client, lambda ev: sum(e["type"] == "agent.completed" for e in ev) == 2)
    sent = fake_ollama.chat_requests[-1]["messages"]
    assert sent[0]["role"] == "system" and "Core" in sent[0]["content"]
    assert [m["content"].strip() for m in sent[1:]][:2] == [
        "my name is Sam",
        "Echo from the fake model: my name is Sam",
    ]


def test_cancel_keeps_the_partial_reply(client: TestClient) -> None:
    sent = client.post("/api/v1/chat", json={"text": "[[slow]]"}, headers=AUTH).json()
    _wait_for(client, lambda ev: any(e["type"] == "agent.started" for e in ev))
    time.sleep(0.3)  # let a few of the 50 ms tokens arrive
    assert client.post(f"/api/v1/conversations/{sent['conversation_id']}/cancel", headers=AUTH).json()["cancelled"]
    _wait_for(client, lambda ev: any(e["type"] == "agent.completed" for e in ev))
    messages = client.get(f"/api/v1/conversations/{sent['conversation_id']}/messages", headers=AUTH).json()
    assert messages[-1]["status"] == "cancelled" and messages[-1]["content"].startswith("tick0")


def test_provider_failure_is_reported_not_raised(client: TestClient) -> None:
    client.post("/api/v1/chat", json={"text": "[[fail]]"}, headers=AUTH)
    events = _wait_for(client, lambda ev: any(e["type"] == "chat.failed" for e in ev))
    failed = next(e for e in events if e["type"] == "chat.failed")
    assert failed["payload"]["code"] == "provider" and "500" in failed["payload"]["error"]
    assert client.get("/api/v1/agents", headers=AUTH).json()[0]["status"] == "idle"


def test_missing_model_gives_an_actionable_hint(make_settings: Callable[..., CoreSettings]) -> None:
    empty = FakeOllama(with_models=False).start()
    try:
        with TestClient(create_app(make_settings(ollama_url=empty.url)), base_url=BASE) as c:
            info = c.get("/api/v1/models", headers=AUTH).json()
            assert info["chat_model"] is None and info["chat_model_hint"].startswith("Run: ollama pull")
            c.post("/api/v1/chat", json={"text": "hi"}, headers=AUTH)
            events = _wait_for(c, lambda ev: any(e["type"] == "chat.failed" for e in ev))
            failed = next(e for e in events if e["type"] == "chat.failed")["payload"]
            assert failed["code"] == "no_model" and failed["hint"].startswith("Run: ollama pull")
    finally:
        empty.stop()


def test_safe_mode_disables_agents(make_settings: Callable[..., CoreSettings]) -> None:
    with TestClient(create_app(make_settings(safe_mode=True, start_reason="safe-mode")), base_url=BASE) as c:
        assert c.get("/api/v1/health").json()["safe_mode"] is True
        response = c.post("/api/v1/chat", json={"text": "hi"}, headers=AUTH)
        assert response.status_code == 503 and "safe mode" in response.json()["detail"]
        assert c.get("/api/v1/agents", headers=AUTH).json()[0]["status"] == "disabled"
        types = [e["type"] for e in c.get("/api/v1/events", headers=AUTH).json()["events"]]
        assert "safe_mode.entered" in types and "service.restarted" in types


def test_model_assignment_is_validated_and_audited(client: TestClient) -> None:
    bad = client.put(
        "/api/v1/models/assignments", json={"tier": "local-fast", "model": "fake-embed:latest"}, headers=AUTH
    )
    assert bad.status_code == 400
    ok = client.put(
        "/api/v1/models/assignments", json={"tier": "local-fast", "model": "fake-chat:latest"}, headers=AUTH
    )
    assert ok.json()["assignments"] == {"local-fast": "fake-chat:latest"}
    audit = client.get("/api/v1/audit", headers=AUTH).json()
    assert audit[0]["action"] == "setting.changed" and audit[0]["target_id"] == "model.local-fast"
    assert client.get("/api/v1/audit/verify", headers=AUTH).json()["ok"]


def test_renderer_errors_are_grouped(client: TestClient) -> None:
    report = {
        "service": "renderer",
        "kind": "TypeError",
        "message": "x is undefined",
        "stack": "TypeError: x is undefined\n    at Hud (hud.tsx:12:3)",
    }
    for _ in range(2):
        assert client.post("/api/v1/errors", json=report, headers=AUTH).status_code == 201
    errors = client.get("/api/v1/errors", headers=AUTH).json()
    assert len(errors) == 1 and errors[0]["count"] == 2 and errors[0]["service"] == "renderer"


def test_vitals_hardware_and_recommendation(client: TestClient) -> None:
    vitals = client.get("/api/v1/system/vitals", headers=AUTH).json()
    assert vitals["ollama"]["reachable"] and vitals["rss_bytes"] > 0 and vitals["db_bytes"]["universe"] > 0
    assert client.get("/api/v1/system/hardware", headers=AUTH).json()["ram_bytes"] > 0
    rec = client.get("/api/v1/models/recommendation", headers=AUTH).json()
    assert rec["tier"] in {"cpu", "le-8gb", "12-16gb", "24gb-plus"} and rec["local_fast"]


def test_event_replay_resumes_after_a_seq(client: TestClient) -> None:
    page = client.get("/api/v1/events", headers=AUTH).json()
    last = page["last_seq"]
    client.post("/api/v1/errors", json={"service": "desktop", "kind": "E", "message": "m"}, headers=AUTH)
    newer = client.get(f"/api/v1/events?since_seq={last}", headers=AUTH).json()["events"]
    assert [e["type"] for e in newer] == ["error.raised"]
    with client.websocket_connect(f"{WS}?ticket={_ticket(client)}&since_seq={last}") as ws:
        first = ws.receive_json()
        assert first["replay"] is True and first["event"]["type"] == "error.raised"


def test_token_never_appears_in_logs(make_settings: Callable[..., CoreSettings], tmp_path) -> None:
    from universe_common.log import configure_logging, get_logger, register_secret

    settings = make_settings()
    configure_logging("core-test", settings.log_dir, console=False)
    register_secret(TOKEN)
    get_logger("t").info("leak_attempt", header=f"Bearer {TOKEN}", token=TOKEN)
    text = (settings.log_dir / "core-test.jsonl").read_text()
    assert TOKEN not in text and "[redacted]" in text
