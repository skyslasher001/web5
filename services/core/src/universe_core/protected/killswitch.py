"""The global kill switch (SPEC §15, ARCHITECTURE.md §1.4). PROTECTED CORE.

The state lives in `<data dir>/killswitch.json` so the supervisor can set it even when Core is hung, and a
restarted Core comes back with it still engaged. Engaged means: every agent call is refused, running tasks
are cancelled, pending approvals are refused, and the egress gate closes.
"""

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from universe_common.timeutil import utcnow

FILENAME = "killswitch.json"


class KillSwitchState(BaseModel):
    engaged: bool = False
    since: str | None = None
    via: str | None = None


def read_state(path: Path) -> KillSwitchState:
    try:
        return KillSwitchState.model_validate_json(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return KillSwitchState()
    except (OSError, ValueError):
        # Unreadable or corrupt: fail safe, as if engaged. Releasing it rewrites the file.
        return KillSwitchState(engaged=True, since=utcnow(), via="unreadable state file")


def write_state(path: Path, state: KillSwitchState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".killswitch-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            out.write(state.model_dump_json())
        os.replace(tmp, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)


class KillSwitch:
    def __init__(
        self,
        data_dir: Path,
        *,
        audit: Callable[..., Any],
        publish: Callable[[str, dict[str, Any]], Any],
        on_change: Callable[[bool], Any],
    ) -> None:
        self.path = data_dir / FILENAME
        self._audit = audit
        self._publish = publish
        self._on_change = on_change
        self.state = read_state(self.path)
        if self.state.engaged:
            self._on_change(True)

    @property
    def engaged(self) -> bool:
        return self.state.engaged

    def set(self, engaged: bool, *, via: str, actor: str = "user") -> KillSwitchState:
        """Engage or release from Core's side (writes the file the supervisor also reads)."""
        if engaged != self.state.engaged:
            write_state(self.path, KillSwitchState(engaged=engaged, since=utcnow(), via=via))
        return self.sync(actor=actor)

    def sync(self, *, actor: str = "system") -> KillSwitchState:
        """Re-read the file (the supervisor changed it) and apply any change."""
        state = read_state(self.path)
        changed = state.engaged != self.state.engaged
        self.state = state
        if changed:
            self._on_change(state.engaged)
            self._audit(
                actor=actor,
                action="killswitch",
                target_type="system",
                target_id="killswitch",
                details={"engaged": state.engaged, "via": state.via},
            )
            self._publish("killswitch.engaged" if state.engaged else "killswitch.released", state.model_dump())
        return state

    def status(self) -> dict[str, Any]:
        return json.loads(self.state.model_dump_json())
