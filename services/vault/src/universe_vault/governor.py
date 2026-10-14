"""Background-work switches shared by Core (writes) and workers (read every loop), kept in `settings`.

- `queue.paused`: no background job runs (you paused it, or the PC is on battery).
- `governor.model_hold_until`: jobs that call Ollama wait while you chat, so a reply never queues
  behind embeddings (SPEC §16: realtime beats background).
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from universe_common.timeutil import utcnow
from universe_vault.jobs import CLASSES, MODEL_KINDS, iso, now_dt

PAUSED_KEY = "queue.paused"
HOLD_KEY = "governor.model_hold_until"


@dataclass(frozen=True)
class GovernorState:
    paused: bool
    reason: str | None
    model_hold: bool


def _get(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def _put(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, value, utcnow()),
    )


def state(conn: sqlite3.Connection) -> GovernorState:
    raw = _get(conn, PAUSED_KEY)
    paused = json.loads(raw) if raw else {}
    hold_until = _get(conn, HOLD_KEY)
    return GovernorState(
        paused=bool(paused.get("paused")),
        reason=paused.get("reason"),
        model_hold=bool(hold_until and hold_until > iso(now_dt())),
    )


def set_paused(conn: sqlite3.Connection, paused: bool, reason: str | None = None) -> None:
    _put(conn, PAUSED_KEY, json.dumps({"paused": paused, "reason": reason if paused else None}))


def hold_models(conn: sqlite3.Connection, seconds: float) -> None:
    _put(conn, HOLD_KEY, iso(now_dt() + timedelta(seconds=seconds)))


def claim_filter(conn: sqlite3.Connection) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(priority classes allowed, job kinds excluded) for the next claim."""
    current = state(conn)
    if current.paused:
        return (), ()
    return CLASSES, MODEL_KINDS if current.model_hold else ()
