"""Supervisor state in a JSON file written atomically; independent of SQLite on purpose."""

import json
import os
import threading
from pathlib import Path
from typing import Any

DEFAULT_STATE: dict[str, Any] = {
    "core_boot_failures": 0,
    "safe_mode": False,
    "safe_mode_reason": None,
    "lkg": None,  # {"commit": str, "promoted_at": float}
}


class StateFile:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.data = dict(DEFAULT_STATE)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                self.data.update({k: v for k, v in loaded.items() if k in DEFAULT_STATE})
        except (OSError, ValueError):
            pass

    def update(self, **changes: Any) -> None:
        with self._lock:
            self.data.update(changes)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
            os.replace(tmp, self.path)

    def __getitem__(self, key: str) -> Any:
        return self.data[key]
