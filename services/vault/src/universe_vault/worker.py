"""A pipeline worker process: `python -m universe_vault.worker` (started and restarted by Core, ADR-0010).

It leases jobs from universe.db, runs them at background OS priority, renews its lease while working,
and forwards events and errors to Core over loopback. It exits by itself when Core goes away.
"""

import os
import sqlite3
import sys
import threading
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import psutil

from universe_common.egress import EgressGate
from universe_common.errors import capture_exception
from universe_common.log import configure_logging, get_logger, register_secret
from universe_common.orphan import watch_parent
from universe_common.sqlite import connect
from universe_vault import governor, jobs
from universe_vault.handlers import HANDLERS, Retry, WorkerContext
from universe_vault.jobs import Job
from universe_vault.layout import Vault
from universe_vault.models import SyncOllama
from universe_vault.vectors import VectorStore

log = get_logger(__name__)
HEARTBEAT_S = 30.0
IDLE_S = 0.5


@dataclass
class EventSink:
    """Buffers events and posts them to Core in one request per job. Delivery is best effort:
    the database is the source of truth, events only keep the UI live."""

    post: Callable[[list[dict[str, Any]]], None] | None = None
    buffer: list[dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def __call__(self, event_type: str, payload: dict[str, Any], *, subject_id: str | None = None) -> None:
        with self.lock:
            self.buffer.append(
                {
                    "type": event_type,
                    "payload": payload,
                    "subject_type": "item" if subject_id else None,
                    "subject_id": subject_id,
                }
            )

    def flush(self) -> None:
        with self.lock:
            events, self.buffer = self.buffer, []
        if events and self.post is not None:
            try:
                self.post(events)
            except Exception as exc:
                log.warning("event_delivery_failed", error=str(exc)[:200], count=len(events))


class CoreLink:
    """Loopback calls from a worker to Core's internal endpoints."""

    def __init__(self, core_url: str, token: str, gate: EgressGate) -> None:
        self._http = gate.client(purpose="core-internal", local_only=True, base_url=core_url, timeout=5.0)
        self._headers = {"Authorization": f"Bearer {token}"}

    def post_events(self, events: list[dict[str, Any]]) -> None:
        response = self._http.post("/api/v1/internal/events", json={"events": events}, headers=self._headers)
        response.raise_for_status()

    def report_error(self, kind: str, message: str, stack: str) -> None:
        try:
            self._http.post(
                "/api/v1/internal/errors",
                json={"service": "worker", "kind": kind, "message": message, "stack": stack},
                headers=self._headers,
            )
        except httpx.HTTPError as exc:
            log.warning("error_report_failed", error=str(exc)[:200])

    def close(self) -> None:
        self._http.close()


def _heartbeat(db_path: Path, job_id: str, worker_id: str, done: threading.Event) -> None:
    conn = connect(db_path)
    try:
        while not done.wait(HEARTBEAT_S):
            if not jobs.heartbeat(conn, job_id, worker_id):
                return
    finally:
        conn.close()


def execute(ctx: WorkerContext, job: Job) -> str:
    """Run one leased job and record the outcome. Returns the job's new status."""
    handler = HANDLERS.get(job.kind)
    done = threading.Event()
    beat = threading.Thread(target=_heartbeat, args=(ctx.vault.db_path, job.id, ctx.worker_id, done), daemon=True)
    beat.start()
    try:
        if handler is None:
            raise ValueError(f"unknown job kind: {job.kind}")
        result = handler(ctx, job)
    except Retry as retry:
        jobs.release(ctx.conn, job.id, ctx.worker_id, delay_s=retry.delay_s)
        log.info("job_released", job_id=job.id, kind=job.kind, reason=str(retry)[:200])
        return "queued"
    except Exception as exc:
        captured = capture_exception(exc, {"job_kind": job.kind, "item_id": job.item_id})
        status = jobs.fail(ctx.conn, job.id, ctx.worker_id, f"{captured.kind}: {captured.message}")
        payload = {"job_id": job.id, "kind": job.kind, "item_id": job.item_id, "error": captured.message[:300]}
        ctx.emit("job.dead" if status == "dead" else "job.failed", payload, subject_id=job.item_id)
        log.warning("job_failed", job_id=job.id, kind=job.kind, status=status, error=captured.message[:300])
        if status == "dead":
            ctx.report_error(captured.kind, captured.message, captured.stack or traceback.format_exc())
        return status
    else:
        jobs.complete(ctx.conn, job.id, ctx.worker_id, result)
        return "succeeded"
    finally:
        done.set()
        ctx.flush_events()


def run(ctx: WorkerContext, stop: threading.Event, *, idle_s: float = IDLE_S) -> None:
    log.info("worker_started", worker_id=ctx.worker_id, pid=os.getpid())
    while not stop.is_set():
        classes, exclude = governor.claim_filter(ctx.conn)
        job = jobs.claim(ctx.conn, ctx.worker_id, classes=classes, exclude_kinds=exclude)
        if job is None:
            stop.wait(idle_s)
            continue
        execute(ctx, job)
    log.info("worker_stopped", worker_id=ctx.worker_id)


def drain(ctx: WorkerContext, *, max_jobs: int = 10_000) -> int:
    """Run jobs until none can be claimed (tests and one-shot tools). Returns the number run."""
    count = 0
    while count < max_jobs:
        classes, exclude = governor.claim_filter(ctx.conn)
        job = jobs.claim(ctx.conn, ctx.worker_id, classes=classes, exclude_kinds=exclude)
        if job is None:
            break
        execute(ctx, job)
        count += 1
    return count


def build_context(
    vault: Vault,
    *,
    worker_id: str,
    ollama_url: str | None,
    sink: EventSink | None = None,
    report_error: Callable[[str, str, str], None] | None = None,
    gate: EgressGate | None = None,
    conn: sqlite3.Connection | None = None,
) -> WorkerContext:
    vault.ensure()
    sink = sink or EventSink()
    ctx = WorkerContext(
        conn=conn or connect(vault.db_path),
        vault=vault,
        worker_id=worker_id,
        ollama=SyncOllama(ollama_url, gate) if ollama_url else None,
        vectors=VectorStore(vault.vectors),
        emit=sink,
    )
    if report_error is not None:
        ctx.report_error = report_error
    ctx.flush_events = sink.flush
    return ctx


def _lower_priority() -> None:
    try:
        proc = psutil.Process()
        if sys.platform == "win32":
            proc.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        else:
            proc.nice(10)
    except (psutil.Error, OSError) as exc:
        log.warning("priority_not_lowered", error=str(exc))


def main() -> int:
    env = os.environ
    worker_id = env.get("UNIVERSE_WORKER_ID", f"worker-{os.getpid()}")
    data_dir = Path(env.get("UNIVERSE_DATA_DIR", "."))
    configure_logging(worker_id, data_dir / "logs", console=False)
    token = env.get("UNIVERSE_INTERNAL_TOKEN", "")
    register_secret(token)
    _lower_priority()
    gate = EgressGate(offline=env.get("UNIVERSE_OFFLINE") == "1")
    link = CoreLink(env["UNIVERSE_CORE_URL"], token, gate) if env.get("UNIVERSE_CORE_URL") else None
    sink = EventSink(post=link.post_events if link else None)
    ctx = build_context(
        Vault(Path(env["UNIVERSE_VAULT_DIR"])),
        worker_id=worker_id,
        ollama_url=env.get("UNIVERSE_OLLAMA_URL"),
        sink=sink,
        report_error=link.report_error if link else None,
        gate=gate,
    )
    stop = threading.Event()
    watch_parent(stop.set)
    try:
        run(ctx, stop)
    finally:
        if ctx.ollama is not None:
            ctx.ollama.close()
        if link is not None:
            link.close()
        ctx.conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
