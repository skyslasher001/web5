"""Core state (event bus queues, asyncio tasks, the shared SQLite connections) may only be touched on the
event-loop thread. FastAPI runs plain `def` handlers in a thread pool, so every handler must be async."""

import inspect
import time

from fastapi.routing import APIRoute, APIWebSocketRoute
from fastapi.testclient import TestClient

from tests.conftest import AUTH
from universe_core.app import create_app
from universe_core.settings import CoreSettings

WS = "ws://127.0.0.1:47999/ws"


def _routes(routes: list) -> list:
    """Flatten routes; FastAPI ≥ 0.140 keeps included routers nested (`original_router`)."""
    out = []
    for route in routes:
        nested = getattr(route, "original_router", None)
        out.extend(_routes(nested.routes) if nested is not None else [route])
    return out


def test_every_route_handler_is_async() -> None:
    app = create_app(CoreSettings(session_token="x" * 32))
    handlers = [r for r in _routes(app.routes) if isinstance(r, APIRoute | APIWebSocketRoute)]
    assert len(handlers) > 15  # the walk really reached the API routes
    sync = [r.path for r in handlers if not inspect.iscoroutinefunction(r.endpoint)]
    assert sync == [], f"these handlers must be `async def`: {sync}"


def test_events_published_by_rest_handlers_reach_websockets_promptly(client: TestClient) -> None:
    ticket = client.post("/api/v1/session/ws-ticket", headers=AUTH).json()["ticket"]
    with client.websocket_connect(f"{WS}?ticket={ticket}") as ws:
        ws.send_json({"op": "ping"})
        assert ws.receive_json()["kind"] == "pong"
        started = time.monotonic()
        report = {"service": "renderer", "kind": "TypeError", "message": "boom"}
        assert client.post("/api/v1/errors", json=report, headers=AUTH).status_code == 201
        message = ws.receive_json()
        assert message["event"]["type"] == "error.raised"
        assert time.monotonic() - started < 2.0


def test_cancel_over_rest_stops_the_stream(client: TestClient) -> None:
    sent = client.post("/api/v1/chat", json={"text": "[[slow]]"}, headers=AUTH).json()
    time.sleep(0.3)
    assert client.post(f"/api/v1/conversations/{sent['conversation_id']}/cancel", headers=AUTH).json()["cancelled"]
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        types = [e["type"] for e in client.get("/api/v1/events", headers=AUTH).json()["events"]]
        if "agent.completed" in types:
            break
        time.sleep(0.05)
    messages = client.get(f"/api/v1/conversations/{sent['conversation_id']}/messages", headers=AUTH).json()
    assert messages[-1]["status"] == "cancelled"
