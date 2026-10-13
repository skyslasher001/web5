"""The egress gate: the only module allowed to create HTTP clients (ARCHITECTURE.md §1.3).

Loopback traffic (Ollama, sibling services) is allowed. Everything else is checked against the
offline switch and the kill switch and recorded through the audit callback.
"""

import ipaddress
from collections.abc import Callable
from typing import Any

import httpx

AuditFn = Callable[[dict[str, Any]], object]

_LOOPBACK_NAMES = {"localhost", "127.0.0.1", "::1"}


class EgressDenied(httpx.HTTPError):
    """Raised when a request is blocked by the offline switch, kill switch or a local-only client."""


def is_loopback(host: str) -> bool:
    host = host.strip("[]").lower()
    if host in _LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


class EgressGate:
    def __init__(self, *, offline: bool = False, audit: AuditFn | None = None) -> None:
        self.offline = offline
        self.killed = False
        self._audit = audit

    def check(self, url: httpx.URL, *, purpose: str, local_only: bool, actor: str) -> None:
        if is_loopback(url.host):
            return
        if local_only:
            raise EgressDenied(f"{purpose}: client is loopback-only, refused {url.host}")
        if self.killed:
            raise EgressDenied(f"{purpose}: kill switch engaged")
        if self.offline:
            raise EgressDenied(f"{purpose}: offline mode is on")
        if self._audit is not None:
            self._audit(
                {
                    "action": "net.request",
                    "actor": actor,
                    "target_type": "host",
                    "target_id": url.host,
                    "details": {"purpose": purpose, "scheme": url.scheme, "path": url.path},
                }
            )

    def async_client(
        self,
        *,
        purpose: str,
        local_only: bool = False,
        actor: str = "system",
        timeout: float | httpx.Timeout = 30.0,
        base_url: str = "",
    ) -> httpx.AsyncClient:
        async def on_request(request: httpx.Request) -> None:
            self.check(request.url, purpose=purpose, local_only=local_only, actor=actor)

        return httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout,
            event_hooks={"request": [on_request]},
            # Loopback clients must never be routed through a system proxy.
            trust_env=not local_only,
        )

    def client(
        self,
        *,
        purpose: str,
        local_only: bool = False,
        actor: str = "system",
        timeout: float | httpx.Timeout = 30.0,
        base_url: str = "",
    ) -> httpx.Client:
        """The synchronous twin of `async_client`, for worker processes."""

        def on_request(request: httpx.Request) -> None:
            self.check(request.url, purpose=purpose, local_only=local_only, actor=actor)

        return httpx.Client(
            base_url=base_url,
            timeout=timeout,
            event_hooks={"request": [on_request]},
            trust_env=not local_only,
        )
