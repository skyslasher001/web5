"""Error store: grouped by fingerprint, emitted as `error.raised` (Forge's input from Phase 5)."""

import json
import sqlite3
from typing import Any, Literal

from pydantic import BaseModel

from universe_common.ids import uuid7
from universe_common.log import get_logger
from universe_common.timeutil import utcnow
from universe_core.events import EventBus

log = get_logger(__name__)

Severity = Literal["warning", "error", "critical"]


class ErrorRecord(BaseModel):
    id: str
    fingerprint: str
    service: str
    kind: str
    message: str
    count: int
    first_seen: str
    last_seen: str
    severity: Severity
    status: str


class ErrorStore:
    def __init__(self, conn: sqlite3.Connection, bus: EventBus) -> None:
        self._conn = conn
        self._bus = bus

    def record(
        self,
        *,
        service: str,
        kind: str,
        message: str,
        stack: str,
        fingerprint: str,
        context: dict[str, Any] | None = None,
        severity: Severity = "error",
    ) -> ErrorRecord | None:
        """Never raises: error capture must not create new errors."""
        now = utcnow()
        try:
            row = self._conn.execute(
                "INSERT INTO errors (id, fingerprint, service, kind, message, stack, context, first_seen,"
                " last_seen, severity) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(fingerprint) DO UPDATE SET count = count + 1, last_seen = excluded.last_seen,"
                " message = excluded.message, stack = excluded.stack, context = excluded.context,"
                " status = CASE WHEN status = 'fixed' THEN 'new' ELSE status END"
                " RETURNING *",
                (
                    uuid7(),
                    fingerprint,
                    service,
                    kind,
                    message,
                    stack,
                    json.dumps(context or {}, ensure_ascii=False, default=str),
                    now,
                    now,
                    severity,
                ),
            ).fetchone()
            record = ErrorRecord(**{k: row[k] for k in ErrorRecord.model_fields})
            self._bus.publish(
                "error.raised",
                {
                    "error_id": record.id,
                    "fingerprint": fingerprint,
                    "service": service,
                    "kind": kind,
                    "message": message[:300],
                    "count": record.count,
                    "severity": severity,
                },
                subject_type="error",
                subject_id=record.id,
            )
            return record
        except Exception:
            log.exception("error_store_record_failed", service=service, kind=kind)
            return None

    def list(self, *, limit: int = 100) -> list[ErrorRecord]:
        rows = self._conn.execute("SELECT * FROM errors ORDER BY last_seen DESC LIMIT ?", (min(limit, 1000),))
        return [ErrorRecord(**{k: row[k] for k in ErrorRecord.model_fields}) for row in rows]
