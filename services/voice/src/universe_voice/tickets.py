"""Single-use, short-lived tickets for the voice WebSocket (ARCHITECTURE §1.3).

Browsers can't set headers on a WebSocket, so the renderer asks Core for a ticket and puts it in the URL. Core
and the voice process share a per-boot key; a ticket is an expiry and a nonce signed with HMAC-SHA256. The voice
process checks the signature and the expiry and remembers nonces, so a ticket works once.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Callable

TTL_S = 30.0


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def mint(key: bytes, *, ttl_s: float = TTL_S, now: Callable[[], float] = time.time) -> str:
    body = _b64(json.dumps({"exp": now() + ttl_s, "n": secrets.token_urlsafe(12)}).encode())
    sig = _b64(hmac.new(key, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


class TicketChecker:
    def __init__(self, key: bytes, now: Callable[[], float] = time.time) -> None:
        self._key, self._now = key, now
        self._used: dict[str, float] = {}

    def check(self, ticket: str) -> bool:
        body, _, sig = ticket.partition(".")
        if not body or not sig:
            return False
        expected = _b64(hmac.new(self._key, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(expected, sig):
            return False
        try:
            claims = json.loads(_unb64(body))
            exp, nonce = float(claims["exp"]), str(claims["n"])
        except (ValueError, KeyError, TypeError):
            return False
        now = self._now()
        self._used = {n: e for n, e in self._used.items() if e > now}  # forget expired nonces
        if exp <= now or nonce in self._used:
            return False
        self._used[nonce] = exp
        return True
