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
