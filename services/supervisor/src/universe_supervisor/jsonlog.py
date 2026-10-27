"""Minimal JSON-lines logger (stdlib only) for the supervisor's own log."""

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any


class JsonLog:
    def __init__(self, path: Path | None, *, echo: bool = True, max_bytes: int = 5 * 1024 * 1024) -> None:
        self._path = path
        self._echo = echo
        self._max_bytes = max_bytes
        self._lock = threading.Lock()
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, event: str, level: str = "info", **fields: Any) -> None:
        record = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
            "level": level,
            "logger": "supervisor",
            "event": event,
            **fields,
        }
        line = json.dumps(record, default=str)
        with self._lock:
            if self._path is not None:
                try:
                    if self._path.exists() and self._path.stat().st_size > self._max_bytes:
                        self._path.replace(self._path.with_suffix(".jsonl.1"))
                    with self._path.open("a", encoding="utf-8") as fh:
                        fh.write(line + "\n")
                except OSError:
                    pass
            if self._echo:
                print(line, file=sys.stderr, flush=True)
