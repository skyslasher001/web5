"""Append-only, hash-chained audit log writer (SPEC §17, ARCHITECTURE.md §4.3). PROTECTED CORE.

Only this module writes audit.db. Details must hold ids and hashes, never vault content or titles.
"""

import hashlib
import json
import sqlite3
import threading
from typing import Any

from pydantic import BaseModel

from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow

GENESIS = "0" * 64


def canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain_hash(prev_hash: str, record: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical(record)).encode("utf-8")).hexdigest()


class AuditVerification(BaseModel):
    ok: bool
    count: int
    first_bad_seq: int | None = None


class AuditEntry(BaseModel):
    seq: int
    ts: str
    actor: str
    action: str
    target_type: str | None
    target_id: str | None
    details: dict[str, Any]
    outcome: str
    task_id: str | None


class AuditWriter:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._lock = threading.Lock()

    def append(
        self,
        *,
        actor: str,
        action: str,
        target_type: str | None = None,
        target_id: str | None = None,
        details: dict[str, Any] | None = None,
        outcome: str = "ok",
        task_id: str | None = None,
    ) -> int:
        with self._lock, transaction(self._conn):
            last = self._conn.execute("SELECT seq, hash FROM audit_log ORDER BY seq DESC LIMIT 1").fetchone()
            seq = last["seq"] + 1 if last else 1
            prev_hash = last["hash"] if last else GENESIS
            record = {
                "seq": seq,
                "ts": utcnow(),
                "actor": actor,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "details": details or {},
                "outcome": outcome,
                "task_id": task_id,
            }
            digest = chain_hash(prev_hash, record)
            self._conn.execute(
                "INSERT INTO audit_log (seq, ts, actor, action, target_type, target_id, details, outcome,"
                " task_id, prev_hash, hash) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    seq,
                    record["ts"],
                    actor,
                    action,
                    target_type,
                    target_id,
                    canonical(record["details"]),
                    outcome,
                    task_id,
                    prev_hash,
                    digest,
                ),
            )
        return seq

    def verify(self) -> AuditVerification:
        prev_hash = GENESIS
        count = 0
        for row in self._conn.execute("SELECT * FROM audit_log ORDER BY seq"):
            count += 1
            record = {
                "seq": row["seq"],
                "ts": row["ts"],
                "actor": row["actor"],
                "action": row["action"],
                "target_type": row["target_type"],
                "target_id": row["target_id"],
                "details": json.loads(row["details"]),
                "outcome": row["outcome"],
                "task_id": row["task_id"],
            }
            if row["prev_hash"] != prev_hash or row["hash"] != chain_hash(prev_hash, record):
                return AuditVerification(ok=False, count=count, first_bad_seq=row["seq"])
            prev_hash = row["hash"]
        return AuditVerification(ok=True, count=count)

    def list(self, *, limit: int = 100, action: str | None = None) -> list[AuditEntry]:
        sql = "SELECT * FROM audit_log"
        params: list[Any] = []
        if action:
            sql += " WHERE action = ?"
            params.append(action)
        sql += " ORDER BY seq DESC LIMIT ?"
        params.append(min(limit, 1000))
        return [
            AuditEntry(
                **{
                    **{k: row[k] for k in AuditEntry.model_fields if k != "details"},
                    "details": json.loads(row["details"]),
                }
            )
            for row in self._conn.execute(sql, params)
        ]
