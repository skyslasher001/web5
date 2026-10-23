"""The SQLite job queue (ADR-0002): priority classes, leases that survive crashes, retries with backoff.

A worker claims one job atomically with `UPDATE … RETURNING`, renews the lease while it runs, then
completes or fails it. An expired lease (the worker died) puts the job back in the queue. After
`max_attempts` the job is `dead` and reported. Stages chain by enqueueing the next job on success.
"""

import json
import random
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from universe_common.ids import uuid7
from universe_vault.schemas import JobInfo, QueueStats

PriorityClass = Literal["realtime", "interactive", "background"]
CLASSES: tuple[PriorityClass, ...] = ("realtime", "interactive", "background")
MODEL_KINDS = ("embed", "caption")  # need Ollama; held back while you chat
LEASE_S = 120.0
BACKOFF_BASE_S = 5.0
BACKOFF_MAX_S = 3600.0


def iso(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def now_dt() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class Job:
    id: str
    kind: str
    item_id: str | None
    priority_class: str
    priority: int
    attempts: int
    max_attempts: int
    payload: dict[str, Any]

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Job":
        return cls(
            id=row["id"],
            kind=row["kind"],
            item_id=row["item_id"],
            priority_class=row["priority_class"],
            priority=row["priority"],
            attempts=row["attempts"],
            max_attempts=row["max_attempts"],
            payload=json.loads(row["payload"] or "{}"),
        )


def enqueue(
    conn: sqlite3.Connection,
    kind: str,
    *,
    item_id: str | None = None,
    payload: dict[str, Any] | None = None,
    priority_class: PriorityClass = "background",
    priority: int = 0,
    max_attempts: int = 5,
    delay_s: float = 0.0,
    idempotency_key: str | None = None,
) -> str | None:
    """Queue a job. With an `idempotency_key`, an identical job still waiting to run is reused (returns its id)."""
    now = now_dt()
    job_id = uuid7()
    cursor = conn.execute(
        "INSERT OR IGNORE INTO jobs (id, kind, item_id, priority_class, priority, status, max_attempts, run_after,"
        " payload, idempotency_key, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
        (
            job_id,
            kind,
            item_id,
            priority_class,
            priority,
            max_attempts,
            iso(now + timedelta(seconds=delay_s)),
            json.dumps(payload or {}),
            idempotency_key,
            iso(now),
            iso(now),
        ),
    )
    if cursor.rowcount:
        return job_id
    row = conn.execute("SELECT id FROM jobs WHERE idempotency_key = ?", (idempotency_key,)).fetchone()
    return row["id"] if row else None


def requeue_expired(conn: sqlite3.Connection) -> int:
    """Leases that ran out (the worker died) go back to the queue, or die if out of attempts."""
    now = iso(now_dt())
    conn.execute(
        "UPDATE jobs SET status = 'dead', lease_owner = NULL, lease_expires_at = NULL, finished_at = ?,"
        " idempotency_key = NULL, updated_at = ?, error = COALESCE(error, 'worker lost its lease')"
        " WHERE status = 'leased' AND lease_expires_at < ? AND attempts >= max_attempts",
        (now, now, now),
    )
    cursor = conn.execute(
        "UPDATE jobs SET status = 'queued', lease_owner = NULL, lease_expires_at = NULL, updated_at = ?"
        " WHERE status = 'leased' AND lease_expires_at < ?",
        (now, now),
    )
    return cursor.rowcount


def claim(
    conn: sqlite3.Connection,
    worker_id: str,
    *,
    classes: tuple[str, ...] = CLASSES,
    exclude_kinds: tuple[str, ...] = (),
    lease_s: float = LEASE_S,
) -> Job | None:
    if not classes:
        return None
    requeue_expired(conn)
    now = now_dt()
    class_marks = ",".join("?" * len(classes))
    kind_clause = f" AND kind NOT IN ({','.join('?' * len(exclude_kinds))})" if exclude_kinds else ""
    row = conn.execute(
        # The key goes on claim, not on finish: work queued while this job runs (a save after it read the file)
        # must be a new job, not folded into one that has already started.
        "UPDATE jobs SET status = 'leased', lease_owner = ?, lease_expires_at = ?, attempts = attempts + 1,"  # noqa: S608
        " idempotency_key = NULL, updated_at = ?"
        " WHERE id = (SELECT id FROM jobs WHERE status = 'queued' AND run_after <= ?"
        f" AND priority_class IN ({class_marks}){kind_clause}"
        " ORDER BY CASE priority_class WHEN 'realtime' THEN 0 WHEN 'interactive' THEN 1 ELSE 2 END,"
        " priority DESC, run_after, id LIMIT 1) AND status = 'queued' RETURNING *",
        (worker_id, iso(now + timedelta(seconds=lease_s)), iso(now), iso(now), *classes, *exclude_kinds),
    ).fetchone()
    return Job.from_row(row) if row else None


def heartbeat(conn: sqlite3.Connection, job_id: str, worker_id: str, *, lease_s: float = LEASE_S) -> bool:
    cursor = conn.execute(
        "UPDATE jobs SET lease_expires_at = ?, updated_at = ? WHERE id = ? AND lease_owner = ? AND status = 'leased'",
        (iso(now_dt() + timedelta(seconds=lease_s)), iso(now_dt()), job_id, worker_id),
    )
    return bool(cursor.rowcount)


def progress(conn: sqlite3.Connection, job_id: str, value: float) -> None:
    conn.execute("UPDATE jobs SET progress = ? WHERE id = ?", (max(0.0, min(1.0, value)), job_id))


def complete(conn: sqlite3.Connection, job_id: str, worker_id: str, result: dict[str, Any] | None = None) -> bool:
    now = iso(now_dt())
    cursor = conn.execute(
        "UPDATE jobs SET status = 'succeeded', result = ?, progress = 1, lease_owner = NULL, lease_expires_at = NULL,"
        " idempotency_key = NULL, error = NULL, finished_at = ?, updated_at = ?"
        " WHERE id = ? AND lease_owner = ? AND status = 'leased'",
        (json.dumps(result or {}), now, now, job_id, worker_id),
    )
    return bool(cursor.rowcount)


def backoff_s(attempts: int) -> float:
    base = min(BACKOFF_MAX_S, BACKOFF_BASE_S * (2 ** max(0, attempts - 1)))
    return base * random.uniform(0.8, 1.2)  # noqa: S311 - jitter, not security


def fail(
    conn: sqlite3.Connection, job_id: str, worker_id: str, error: str, *, retryable: bool = True
) -> Literal["queued", "dead", "lost"]:
    row = conn.execute(
        "SELECT attempts, max_attempts FROM jobs WHERE id = ? AND lease_owner = ? AND status = 'leased'",
        (job_id, worker_id),
    ).fetchone()
    if row is None:
        return "lost"
    now = now_dt()
    if retryable and row["attempts"] < row["max_attempts"]:
        conn.execute(
            "UPDATE jobs SET status = 'queued', error = ?, run_after = ?, lease_owner = NULL, lease_expires_at = NULL,"
            " updated_at = ? WHERE id = ?",
            (error[:4000], iso(now + timedelta(seconds=backoff_s(row["attempts"]))), iso(now), job_id),
        )
        return "queued"
    conn.execute(
        "UPDATE jobs SET status = 'dead', error = ?, lease_owner = NULL, lease_expires_at = NULL,"
        " idempotency_key = NULL, finished_at = ?, updated_at = ? WHERE id = ?",
        (error[:4000], iso(now), iso(now), job_id),
    )
    return "dead"


def release(conn: sqlite3.Connection, job_id: str, worker_id: str, *, delay_s: float) -> None:
    """Give a job back without counting the attempt (e.g. the model server is busy or held)."""
    now = now_dt()
    conn.execute(
        "UPDATE jobs SET status = 'queued', attempts = MAX(0, attempts - 1), run_after = ?, lease_owner = NULL,"
        " lease_expires_at = NULL, updated_at = ? WHERE id = ? AND lease_owner = ?",
        (iso(now + timedelta(seconds=delay_s)), iso(now), job_id, worker_id),
    )


def retry(conn: sqlite3.Connection, job_id: str) -> bool:
    now = iso(now_dt())
    cursor = conn.execute(
        "UPDATE jobs SET status = 'queued', attempts = 0, run_after = ?, error = NULL, finished_at = NULL,"
        " updated_at = ? WHERE id = ? AND status IN ('dead', 'cancelled')",
        (now, now, job_id),
    )
    return bool(cursor.rowcount)


def cancel(conn: sqlite3.Connection, job_id: str) -> bool:
    now = iso(now_dt())
    cursor = conn.execute(
        "UPDATE jobs SET status = 'cancelled', idempotency_key = NULL, finished_at = ?, updated_at = ?"
        " WHERE id = ? AND status = 'queued'",
        (now, now, job_id),
    )
    return bool(cursor.rowcount)


def get(conn: sqlite3.Connection, job_id: str) -> JobInfo | None:
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    return _info(row) if row else None


def _info(row: sqlite3.Row) -> JobInfo:
    columns = set(row.keys())
    return JobInfo(**{k: row[k] for k in JobInfo.model_fields if k in columns})


def list_jobs(
    conn: sqlite3.Connection, *, status: str | None = None, kind: str | None = None, limit: int = 100
) -> list[JobInfo]:
    clauses, params = ["1 = 1"], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if kind:
        clauses.append("kind = ?")
        params.append(kind)
    rows = conn.execute(
        f"SELECT * FROM jobs WHERE {' AND '.join(clauses)} ORDER BY updated_at DESC LIMIT ?",  # noqa: S608
        (*params, max(1, min(limit, 500))),
    ).fetchall()
    return [_info(row) for row in rows]


def stats(
    conn: sqlite3.Connection, *, paused: bool, pause_reason: str | None, model_hold: bool, workers: int
) -> QueueStats:
    counts = {row["status"]: row["n"] for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")}
    by_kind = {
        row["kind"]: row["n"]
        for row in conn.execute(
            "SELECT kind, COUNT(*) AS n FROM jobs WHERE status IN ('queued', 'leased') GROUP BY kind"
        )
    }
    hour_ago = iso(now_dt() - timedelta(hours=1))
    done = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE status = 'succeeded' AND finished_at >= ?", (hour_ago,)
    ).fetchone()[0]
    return QueueStats(
        queued=counts.get("queued", 0),
        leased=counts.get("leased", 0),
        dead=counts.get("dead", 0),
        succeeded_last_hour=done,
        by_kind=by_kind,
        paused=paused,
        pause_reason=pause_reason,
        model_hold=model_hold,
        workers=workers,
    )


def prune_finished(conn: sqlite3.Connection, *, older_than_days: int = 7) -> int:
    """Succeeded and cancelled jobs are history; keep a week of it."""
    cutoff = iso(now_dt() - timedelta(days=older_than_days))
    cursor = conn.execute("DELETE FROM jobs WHERE status IN ('succeeded', 'cancelled') AND finished_at < ?", (cutoff,))
    return cursor.rowcount
