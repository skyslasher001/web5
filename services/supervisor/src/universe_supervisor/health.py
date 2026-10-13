"""Loopback HTTP health checks (stdlib). Never routed through a proxy."""

import json
import urllib.error
import urllib.request
from typing import Any

_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def get_json(url: str, timeout: float = 1.0) -> Any | None:
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("health checks are loopback-only")
    try:
        with _opener.open(url, timeout=timeout) as response:
            if response.status != 200:
                return None
            return json.loads(response.read() or b"null")
    except (urllib.error.URLError, OSError, ValueError):
        return None


def post_json(url: str, *, token: str, body: Any = None, timeout: float = 1.0) -> Any | None:
    """POST to a loopback service with a bearer token. None when it doesn't answer 2xx in time."""
    if not url.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("loopback only")
    data = json.dumps(body if body is not None else {}).encode()
    request = urllib.request.Request(  # noqa: S310 - loopback http only, checked above
        url, data=data, method="POST", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    )
    try:
        with _opener.open(request, timeout=timeout) as response:
            return json.loads(response.read() or b"null") if 200 <= response.status < 300 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None
