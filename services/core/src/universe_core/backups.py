"""Backup service in Core: configuration, the daily schedule, and runs in the background (SPEC §18).

Configuration lives in `settings` (`backup.config`); the repository password lives in the OS credential
store. Runs happen in a thread; progress and results are published as events.
"""

import asyncio
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from universe_common.errors import capture_exception
from universe_common.log import get_logger
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_vault import backup, governor
from universe_vault.layout import Vault

log = get_logger(__name__)
CONFIG_KEY = "backup.config"


class BackupConfigRequest(BaseModel):
    target: str = Field(min_length=1, max_length=4096)
    password: str = Field(min_length=12, max_length=500)
    enabled: bool = True
    schedule_hour: int = Field(default=3, ge=0, le=23)
    restic_path: str | None = Field(default=None, max_length=4096)


class BackupRecord(ApiModel):
    id: str
    kind: str
    status: str
    restic_snapshot_id: str | None = None
    files_new: int | None = None
    bytes_added: int | None = None
    error: str | None = None
    started_at: str
    finished_at: str | None = None
    verified_at: str | None = None


class BackupStatus(ApiModel):
    configured: bool
    target: str | None = None
    enabled: bool = False
    schedule_hour: int = 3
    restic_found: bool
    restic_path: str | None = None
    install_hint: str = "winget install restic.restic"
    password_stored: bool = False
    running: bool = False
    last: BackupRecord | None = None
    last_success: BackupRecord | None = None


class Snapshot(ApiModel):
    id: str
    short_id: str
    time: str
    tags: list[str] = Field(default_factory=list)


class RestoreRequest(BaseModel):
    snapshot_id: str = Field(min_length=6, max_length=80, pattern=r"^[0-9a-f]+$")
    target: str = Field(min_length=1, max_length=4096)


def _record(row: sqlite3.Row | None) -> BackupRecord | None:
    return BackupRecord(**{k: row[k] for k in BackupRecord.model_fields}) if row else None


class BackupService:
    def __init__(
        self,
        *,
        vault: Vault,
        run_db: Callable[..., Any],
        publish: Callable[..., Any],
        record_error: Callable[[BaseException], None],
    ) -> None:
        self.vault = vault
        self._run_db = run_db
        self._publish = publish
        self._record_error = record_error
        self._task: asyncio.Task[Any] | None = None

    # ---------- config ----------

    @staticmethod
    def config(conn: sqlite3.Connection) -> dict[str, Any]:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (CONFIG_KEY,)).fetchone()
        return json.loads(row["value"]) if row else {}

    def _restic(self, conn: sqlite3.Connection) -> backup.Restic:
        config = self.config(conn)
        if not config.get("target"):
            raise backup.BackupError("Backups aren't set up yet.")
        exe = backup.find_restic(config.get("restic_path"))
        if exe is None:
            raise backup.BackupError("restic isn't installed (winget install restic.restic).")
        password = backup.load_password(config["target"])
        if not password:
            raise backup.BackupError("The backup password isn't in the credential store; set backups up again.")
        return backup.Restic(exe, config["target"], password)

    def _status(self, conn: sqlite3.Connection) -> BackupStatus:
        config = self.config(conn)
        exe = backup.find_restic(config.get("restic_path"))
        last = conn.execute("SELECT * FROM backups ORDER BY started_at DESC LIMIT 1").fetchone()
        success = conn.execute(
            "SELECT * FROM backups WHERE status = 'succeeded' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        target = config.get("target")
        return BackupStatus(
            configured=bool(target),
            target=target,
            enabled=bool(config.get("enabled")),
            schedule_hour=int(config.get("schedule_hour", 3)),
            restic_found=exe is not None,
            restic_path=str(exe) if exe else None,
            password_stored=bool(target and backup.load_password(target)),
            running=self.running,
            last=_record(last),
            last_success=_record(success),
        )

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    async def status(self) -> BackupStatus:
        return await self._run_db(self._status)

    def _configure(self, conn: sqlite3.Connection, body: BackupConfigRequest) -> None:
        target = Path(body.target).expanduser()
        if not target.is_absolute():
            raise backup.BackupError("Choose an absolute folder for the backups (an external drive or NAS).")
        target = target.resolve()
        if self.vault.contains(target) or self.vault.root.resolve().is_relative_to(target):
            raise backup.BackupError("The backup folder can't be inside the vault, or contain it.")
        exe = backup.find_restic(body.restic_path)
        if exe is None:
            raise backup.BackupError("restic isn't installed (winget install restic.restic).")
        restic = backup.Restic(exe, str(target), body.password)
        if target.exists() and any(target.iterdir()):
            if not restic.initialized():
                raise backup.BackupError(
                    "That folder isn't empty and isn't a backup repository, or the password is wrong."
                )
        else:
            target.mkdir(parents=True, exist_ok=True)
            restic.init()
        backup.store_password(str(target), body.password)
        value = {
            "target": str(target),
            "enabled": body.enabled,
            "schedule_hour": body.schedule_hour,
            "restic_path": str(exe) if body.restic_path else None,
        }
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (CONFIG_KEY, json.dumps(value), utcnow()),
        )

    async def configure(self, body: BackupConfigRequest) -> BackupStatus:
        await self._run_db(self._configure, body)
        return await self.status()

    # ---------- runs ----------

    def _start(self, name: str, work: Callable[[sqlite3.Connection], Any], on_done: Callable[[Any], None]) -> bool:
        if self.running:
            return False

        async def go() -> None:
            try:
                result = await self._run_db(work)
            except backup.BackupError as exc:
                self._publish("backup.failed", {"operation": name, "error": str(exc)})
                log.warning("backup_operation_failed", operation=name, error=str(exc))
            except Exception as exc:
                self._record_error(exc)
                self._publish("backup.failed", {"operation": name, "error": capture_exception(exc).message[:300]})
            else:
                on_done(result)

        self._task = asyncio.create_task(go(), name=f"backup:{name}")
        return True

    def run(self, kind: str = "manual") -> bool:
        def work(conn: sqlite3.Connection) -> dict[str, Any]:
            return backup.run_backup(conn, self.vault, self._restic(conn), kind=kind)

        def done(result: dict[str, Any]) -> None:
            self._publish(
                "backup.completed",
                {
                    "kind": kind,
                    "snapshot_id": result.get("snapshot_id"),
                    "files_new": result.get("files_new"),
                    "bytes_added": result.get("data_added"),
                },
            )

        return self._start("backup", work, done)

    def verify(self) -> bool:
        def work(conn: sqlite3.Connection) -> dict[str, Any]:
            return backup.verify(conn, self.vault, self._restic(conn))

        return self._start("verify", work, lambda result: self._publish("backup.restore_tested", result))

    def restore(self, snapshot_id: str, target: str) -> bool:
        def work(conn: sqlite3.Connection) -> str:
            return str(backup.restore_to(self._restic(conn), self.vault, snapshot_id, Path(target)))

        return self._start(
            "restore", work, lambda path: self._publish("backup.restored", {"snapshot_id": snapshot_id, "target": path})
        )

    async def snapshots(self) -> list[Snapshot]:
        def work(conn: sqlite3.Connection) -> list[Snapshot]:
            raw = self._restic(conn).snapshots()
            return [
                Snapshot(id=s["id"], short_id=s["short_id"], time=s["time"], tags=s.get("tags") or [])
                for s in sorted(raw, key=lambda s: s.get("time", ""), reverse=True)
            ]

        return await self._run_db(work)

    async def history(self, limit: int = 50) -> list[BackupRecord]:
        def work(conn: sqlite3.Connection) -> list[BackupRecord]:
            rows = conn.execute("SELECT * FROM backups ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
            return [r for r in (_record(row) for row in rows) if r is not None]

        return await self._run_db(work)

    # ---------- schedule ----------

    def _due(self, conn: sqlite3.Connection, now: datetime) -> bool:
        config = self.config(conn)
        if not config.get("target") or not config.get("enabled") or governor.state(conn).paused:
            return False
        hour = int(config.get("schedule_hour", 3))
        if now.hour < hour:
            return False
        # Today's slot is covered by any backup since the scheduled hour, manual ones included: a backup you
        # just ran by hand must not be followed by a scheduled one (it also blocked verify and restore).
        slot = now.replace(hour=hour, minute=0, second=0, microsecond=0)  # local time, today
        since = slot.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        done = conn.execute(
            "SELECT 1 FROM backups WHERE kind IN ('scheduled', 'manual') AND status IN ('running', 'succeeded')"
            " AND started_at >= ?",
            (since,),
        ).fetchone()
        recent_failure = conn.execute(
            "SELECT 1 FROM backups WHERE kind = 'scheduled' AND status = 'failed' AND started_at >= ?",
            (utcnow()[:13],),  # at most one retry per hour after a failure
        ).fetchone()
        return done is None and recent_failure is None

    async def tick(self, now: datetime | None = None) -> None:
        if self.running:
            return
        if await self._run_db(self._due, now or datetime.now().astimezone()):
            self.run("scheduled")
