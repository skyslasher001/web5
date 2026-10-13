"""Core's side of the vault: per-thread DB connections, pipeline worker processes, and the governor loop.

- Request handlers run vault work in threads (`VaultDb.run`), each thread with its own SQLite connection,
  so file copies, purges and searches never block the event loop.
- `WorkerManager` starts `python -m universe_vault.worker` processes and restarts them with backoff
  (ADR-0010). They exit by themselves if Core dies.
- `Governor` holds model jobs back while you chat, pauses background work on battery, notices when an
  embedding model appears or changes (and queues re-embedding), and runs daily housekeeping.
"""

import asyncio
import contextlib
import os
import sqlite3
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

import psutil

from universe_common.log import get_logger
from universe_common.sqlite import connect, transaction
from universe_vault import governor, jobs, purge
from universe_vault.layout import Vault

log = get_logger(__name__)
T = TypeVar("T")
CREATE_NO_WINDOW = 0x08000000


class VaultDb:
    """One SQLite connection per thread for vault work done off the event loop."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._local = threading.local()
        self._all: list[sqlite3.Connection] = []
        self._lock = threading.Lock()

    def conn(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = connect(self.path)
            self._local.conn = conn
            with self._lock:
                self._all.append(conn)
        return conn

    async def run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        def call() -> T:
            return fn(self.conn(), *args, **kwargs)

        return await asyncio.to_thread(call)

    def close(self) -> None:
        with self._lock:
            for conn in self._all:
                with contextlib.suppress(sqlite3.ProgrammingError):  # its thread is gone; the OS reclaims it
                    conn.close()
            self._all.clear()


@dataclass
class WorkerProcess:
    index: int
    proc: subprocess.Popen[bytes] | None = None
    restarts: int = 0
    started_at: float = 0.0
    next_start: float = 0.0
    last_exit: int | None = None

    @property
    def worker_id(self) -> str:
        return f"worker-{self.index}"

    def status(self) -> dict[str, Any]:
        alive = self.proc is not None and self.proc.poll() is None
        return {
            "id": self.worker_id,
            "pid": self.proc.pid if alive and self.proc else None,
            "state": "running" if alive else "restarting",
            "restarts": self.restarts,
            "last_exit": self.last_exit,
        }


class WorkerManager:
    BACKOFF_MIN_S = 1.0
    BACKOFF_MAX_S = 30.0
    STABLE_S = 60.0

    def __init__(self, *, count: int, env: dict[str, str], log_dir: Path) -> None:
        self.count = count
        self._env = env
        self._log_dir = log_dir
        self._workers = [WorkerProcess(i + 1) for i in range(count)]
        self._task: asyncio.Task[None] | None = None
        self._stopping = False

    def _spawn(self, worker: WorkerProcess) -> None:
        self._log_dir.mkdir(parents=True, exist_ok=True)
        env = {**self._env, "UNIVERSE_WORKER_ID": worker.worker_id}
        with (self._log_dir / f"{worker.worker_id}.out.log").open("ab") as out:
            worker.proc = subprocess.Popen(
                [sys.executable, "-m", "universe_vault.worker"],
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.STDOUT,
                creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        worker.started_at = time.monotonic()
        log.info("worker_spawned", worker=worker.worker_id, pid=worker.proc.pid)

    async def start(self) -> None:
        if self.count == 0:
            return
        for worker in self._workers:
            self._spawn(worker)
        self._task = asyncio.create_task(self._monitor(), name="worker-monitor")

    async def _monitor(self) -> None:
        while not self._stopping:
            await asyncio.sleep(1.0)
            now = time.monotonic()
            for worker in self._workers:
                if worker.proc is not None and worker.proc.poll() is not None:
                    worker.last_exit = worker.proc.returncode
                    streak = 0 if now - worker.started_at > self.STABLE_S else worker.restarts + 1
                    delay = min(self.BACKOFF_MAX_S, self.BACKOFF_MIN_S * (2 ** max(0, streak - 1))) if streak else 1.0
                    log.error("worker_exited", worker=worker.worker_id, code=worker.last_exit, restart_in_s=delay)
                    worker.proc = None
                    worker.restarts += 1
                    worker.next_start = now + delay
                if worker.proc is None and now >= worker.next_start and not self._stopping:
                    try:
                        self._spawn(worker)
                    except OSError as exc:
                        log.error("worker_spawn_failed", worker=worker.worker_id, error=str(exc))
                        worker.next_start = now + self.BACKOFF_MAX_S

    def status(self) -> list[dict[str, Any]]:
        return [w.status() for w in self._workers]

    async def stop(self) -> None:
        self._stopping = True
        if self._task is not None:
            self._task.cancel()
        procs = [w.proc for w in self._workers if w.proc is not None and w.proc.poll() is None]
        for proc in procs:
            proc.terminate()
        deadline = time.monotonic() + 5
        for proc in procs:
            try:
                await asyncio.to_thread(proc.wait, max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                proc.kill()


def worker_env(
    *, vault_dir: Path, data_dir: Path, core_url: str, internal_token: str, ollama_url: str, offline: bool
) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("UNIVERSE_SESSION", "UNIVERSE_SUPERVISOR"))}
    env.update(
        UNIVERSE_VAULT_DIR=str(vault_dir),
        UNIVERSE_DATA_DIR=str(data_dir),
        UNIVERSE_CORE_URL=core_url,
        UNIVERSE_INTERNAL_TOKEN=internal_token,
        UNIVERSE_OLLAMA_URL=ollama_url,
        UNIVERSE_OFFLINE="1" if offline else "0",
        PYTHONUNBUFFERED="1",
    )
    return env


class Governor:
    """A small loop in Core. Background work yields to you (SPEC §16)."""

    TICK_S = 2.0
    HOLD_S = 10.0
    EMBEDDER_CHECK_S = 60.0
    HOUSEKEEPING_S = 6 * 3600.0

    def __init__(
        self,
        *,
        conn: sqlite3.Connection,
        vault: Vault,
        chat_active: Callable[[], int],
        current_embedder: Callable[[], Any],
        purge_item: Callable[[str], Any],
        publish: Callable[..., Any],
        extra_tick: Callable[[], Any] | None = None,
        battery: Callable[[], Any] = psutil.sensors_battery,
    ) -> None:
        self._conn = conn
        self._vault = vault
        self._chat_active = chat_active
        self._current_embedder = current_embedder
        self._purge_item = purge_item
        self._publish = publish
        self._extra_tick = extra_tick
        self._battery = battery
        self._task: asyncio.Task[None] | None = None
        self._last_embedder_check = 0.0
        self._last_housekeeping = 0.0
        self._paused: bool | None = None

    def start(self) -> None:
        self._task = asyncio.create_task(self._loop(), name="governor")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("governor_tick_failed")
            await asyncio.sleep(self.TICK_S)

    async def tick(self, *, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self._chat_active() > 0:
            governor.hold_models(self._conn, self.HOLD_S)
        self._battery_rule()
        state = governor.state(self._conn)
        if self._paused is not None and state.paused != self._paused:
            event = "governor.paused" if state.paused else "governor.resumed"
            self._publish(event, {"reason": state.reason})
        self._paused = state.paused
        if now - self._last_embedder_check >= self.EMBEDDER_CHECK_S:
            self._last_embedder_check = now
            await self.check_embedder()
        if now - self._last_housekeeping >= self.HOUSEKEEPING_S:
            self._last_housekeeping = now
            await self.housekeeping()
        if self._extra_tick is not None:
            await self._extra_tick()

    def _battery_rule(self) -> None:
        try:
            battery = self._battery()
        except (NotImplementedError, AttributeError, OSError):
            battery = None
        state = governor.state(self._conn)
        on_battery = battery is not None and not battery.power_plugged
        if on_battery and not state.paused:
            governor.set_paused(self._conn, True, "battery")
        elif not on_battery and state.paused and state.reason == "battery":
            governor.set_paused(self._conn, False)

    async def check_embedder(self) -> None:
        """Queue re-embedding when an embedding model appears, changes or is updated."""
        embedder = await self._current_embedder()
        key = f"{embedder.name}@{embedder.digest}" if embedder else ""
        row = self._conn.execute("SELECT value FROM settings WHERE key = 'pipeline.embedder'").fetchone()
        if row is not None and row["value"] == key:
            return
        with transaction(self._conn):
            self._conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES ('pipeline.embedder', ?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, jobs.iso(jobs.now_dt())),
            )
            if embedder is not None:
                jobs.enqueue(self._conn, "reembed", priority=-5, idempotency_key="reembed")
        log.info("embedder_changed", embedder=key or None)

    async def housekeeping(self) -> None:
        for item_id in purge.expired_trash(self._conn):
            await self._purge_item(item_id)
        jobs.prune_finished(self._conn)
