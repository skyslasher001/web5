"""Localhost hardening (ADR-0006): Host and Origin checks, bearer token, single-use WebSocket tickets."""

import json
import secrets
import time
from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

from fastapi import HTTPException, Request, status

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class LocalGuard:
    """Rejects requests whose Host isn't our loopback address (DNS rebinding) or whose Origin isn't allowed."""

    def __init__(self, app: ASGIApp, *, port: int, allowed_origins: tuple[str, ...]) -> None:
        self.app = app
        self.hosts = {f"127.0.0.1:{port}".encode(), f"localhost:{port}".encode()}
        self.origins = {o.encode() for o in allowed_origins}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return
        headers = dict(scope.get("headers") or [])
        problem = None
        if headers.get(b"host") not in self.hosts:
            problem = "Host header is not this service's loopback address"
        elif b"origin" in headers and headers[b"origin"] not in self.origins:
            problem = "Origin is not allowed"
        if problem is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            await receive()  # websocket.connect
            await send({"type": "websocket.close", "code": 4403, "reason": problem})
            return
        body = json.dumps({"type": "about:blank", "title": "Forbidden", "status": 403, "detail": problem}).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 403,
                "headers": [
                    (b"content-type", b"application/problem+json"),
                    (b"content-length", str(len(body)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})


class TokenAuth:
    def __init__(self, token: str) -> None:
        self._expected = f"Bearer {token}"

    def __call__(self, request: Request) -> None:
        supplied = request.headers.get("authorization", "")
        if not secrets.compare_digest(supplied.encode(), self._expected.encode()):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid session token")


class TicketStore:
    """Single-use, short-lived tickets: browsers can't set headers on WebSocket connections."""

    def __init__(self, ttl_s: float = 30.0) -> None:
        self.ttl_s = ttl_s
        self._tickets: dict[str, float] = {}

    def issue(self) -> str:
        now = time.monotonic()
        self._tickets = {t: exp for t, exp in self._tickets.items() if exp > now}
        ticket = secrets.token_urlsafe(24)
        self._tickets[ticket] = now + self.ttl_s
        return ticket

    def consume(self, ticket: str) -> bool:
        expires = self._tickets.pop(ticket, None)
        return expires is not None and expires > time.monotonic()
