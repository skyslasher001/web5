"""Automated, encrypted, versioned backups with restic (SPEC §18, ADR-0010).

- restic is an external binary you install (`winget install restic.restic`), like Ollama.
- The repository password unlocks your data. It's shown to you once at setup (keep it somewhere else:
  without it a backup can't be restored on a new PC) and stored in the OS credential store so scheduled
  runs need no prompt.
- Before each run the three SQLite databases are copied consistently with the SQLite backup API into
  `.universe/backup-staging/`; the live database files are excluded.
- Restores always go to a separate, empty folder. Nothing ever writes over the live vault.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import keyring
import keyring.errors

from universe_common.ids import uuid7
from universe_common.log import get_logger, register_secret
from universe_common.sqlite import snapshot
from universe_common.timeutil import utcnow
from universe_vault.layout import INDEX_DIR, Vault

log = get_logger(__name__)
KEYRING_SERVICE = "UNIVERSE"
STAGING = "backup-staging"
DATABASES = ("universe", "events", "audit")
EXCLUDES = [f"{INDEX_DIR}/{db}.db{suffix}" for db in DATABASES for suffix in ("", "-wal", "-shm")] + [
    f"{INDEX_DIR}/cache",
    f"{INDEX_DIR}/backups",
]
KEEP = {"daily": 7, "weekly": 4, "monthly": 12}
CREATE_NO_WINDOW = 0x08000000


class BackupError(RuntimeError):
    """User-presentable."""


def find_restic(configured: str | None = None) -> Path | None:
    candidates: list[Path] = []
    if configured:
        candidates.append(Path(configured))
    found = shutil.which("restic")
    if found:
        candidates.append(Path(found))
    if sys.platform == "win32":
        local = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        candidates += [
            local / "Microsoft" / "WinGet" / "Links" / "restic.exe",
            Path.home() / "scoop" / "shims" / "restic.exe",
            Path(os.environ.get("PROGRAMFILES", "C:/Program Files")) / "restic" / "restic.exe",
        ]
    return next((c for c in candidates if c.is_file()), None)


def keyring_user(repo: str) -> str:
    return f"restic:{repo}"  # repo paths are resolved once, when backups are configured


def store_password(repo: str, password: str) -> None:
    try:
        keyring.set_password(KEYRING_SERVICE, keyring_user(repo), password)
    except keyring.errors.KeyringError as exc:
        raise BackupError(f"The OS credential store is not available: {exc}") from exc


def load_password(repo: str) -> str | None:
    try:
        password = keyring.get_password(KEYRING_SERVICE, keyring_user(repo))
    except keyring.errors.KeyringError:
        return None
    register_secret(password)
    return password


@dataclass
class Restic:
    exe: Path
    repo: str
    password: str

    def __post_init__(self) -> None:
        register_secret(self.password)

    def run(self, *args: str, timeout: float = 3600, check: bool = True) -> subprocess.CompletedProcess[str]:
        env = {
            **{k: v for k, v in os.environ.items() if not k.startswith(("RESTIC_", "UNIVERSE_SESSION"))},
            "RESTIC_REPOSITORY": self.repo,
            "RESTIC_PASSWORD": self.password,
            "RESTIC_PROGRESS_FPS": "0.2",
        }
        result = subprocess.run(
            [str(self.exe), *args],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            check=False,
        )
        if check and result.returncode != 0:
            raise BackupError(_explain(result.stderr or result.stdout))
        return result

    def version(self) -> str:
        return self.run("version", timeout=30).stdout.strip()

    def initialized(self) -> bool:
        return self.run("cat", "config", timeout=60, check=False).returncode == 0

    def init(self) -> None:
        self.run("init", timeout=120)

    def backup(self, root: Path, *, excludes: list[str], tags: list[str]) -> dict[str, Any]:
        args = ["backup", str(root), "--json", "--one-file-system"]
        for pattern in excludes:
            args += ["--exclude", str(root / pattern)]
        for tag in tags:
            args += ["--tag", tag]
        result = self.run(*args, timeout=24 * 3600)
        summary: dict[str, Any] = {}
        for line in result.stdout.splitlines():
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("message_type") == "summary":
                summary = message
        if not summary.get("snapshot_id"):
            raise BackupError("restic finished without reporting a snapshot")
        return summary

    def snapshots(self) -> list[dict[str, Any]]:
        return json.loads(self.run("snapshots", "--json", timeout=300).stdout or "[]")

    def restore(self, snapshot_id: str, target: Path, *, include: str | None = None) -> None:
        args = ["restore", snapshot_id, "--target", str(target)]
        if include:
            args += ["--include", include]
        self.run(*args, timeout=24 * 3600)

    def check(self) -> None:
        self.run("check", timeout=3600)

    def forget(self) -> None:
        self.run(
            "forget",
            "--keep-daily",
            str(KEEP["daily"]),
            "--keep-weekly",
            str(KEEP["weekly"]),
            "--keep-monthly",
            str(KEEP["monthly"]),
            "--prune",
            timeout=6 * 3600,
        )


def _explain(stderr: str) -> str:
    text = stderr.strip().splitlines()
    message = text[-1] if text else "restic failed"
    lowered = stderr.lower()
    if "wrong password" in lowered or "no key found" in lowered:
        return "Wrong password for this backup repository."
    if "repository does not exist" in lowered or "unable to open config file" in lowered:
        return "No backup repository at that location yet."
    if "no space left" in lowered:
        return "The backup drive is full."
    return message[:500]


def stage_databases(vault: Vault) -> Path:
    """Consistent copies of the live databases, which restic then backs up instead of the live files."""
    staging = vault.index / STAGING
    staging.mkdir(parents=True, exist_ok=True)
    for name in DATABASES:
        live = vault.index / f"{name}.db"
        if not live.exists():
            continue
        source = sqlite3.connect(f"file:{live}?mode=ro", uri=True)
        try:
            tmp = staging / f"{name}.db.tmp"
            tmp.unlink(missing_ok=True)
            snapshot(source, tmp)
            os.replace(tmp, staging / f"{name}.db")
        finally:
            source.close()
    return staging


def run_backup(conn: sqlite3.Connection, vault: Vault, restic: Restic, *, kind: str = "manual") -> dict[str, Any]:
    backup_id = uuid7()
    conn.execute(
        "INSERT INTO backups (id, kind, target, status, started_at) VALUES (?, ?, ?, 'running', ?)",
        (backup_id, kind, restic.repo, utcnow()),
    )
    try:
        stage_databases(vault)
        summary = restic.backup(vault.root, excludes=EXCLUDES, tags=["universe", kind])
        if kind == "scheduled":
            try:
                restic.forget()
            except BackupError as exc:
                log.warning("backup_forget_failed", error=str(exc))
    except (BackupError, OSError, subprocess.TimeoutExpired, sqlite3.Error) as exc:
        conn.execute(
            "UPDATE backups SET status = 'failed', error = ?, finished_at = ? WHERE id = ?",
            (str(exc)[:1000], utcnow(), backup_id),
        )
        raise BackupError(str(exc)) from exc
    conn.execute(
        "UPDATE backups SET status = 'succeeded', restic_snapshot_id = ?, files_new = ?, bytes_added = ?,"
        " finished_at = ? WHERE id = ?",
        (summary["snapshot_id"], summary.get("files_new"), summary.get("data_added"), utcnow(), backup_id),
    )
    return {"id": backup_id, "snapshot_id": summary["snapshot_id"], **summary}


def verify(conn: sqlite3.Connection, vault: Vault, restic: Restic) -> dict[str, Any]:
    """A real test restore: repository check, then restore the newest database copy and open it."""
    restic.check()
    snapshots = restic.snapshots()
    if not snapshots:
        raise BackupError("There is no backup to test yet.")
    latest = max(snapshots, key=lambda s: s.get("time", ""))
    with tempfile.TemporaryDirectory(prefix="universe-restore-test-") as tmp:
        staged = f"{vault.root.resolve().as_posix()}/{INDEX_DIR}/{STAGING}/universe.db"
        restic.restore(latest["short_id"], Path(tmp), include=staged)
        restored = next(Path(tmp).rglob("universe.db"), None)
        if restored is None:
            raise BackupError("The test restore did not contain the database copy.")
        db = sqlite3.connect(restored)
        try:
            integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            items = db.execute("SELECT COUNT(*) FROM items").fetchone()[0]
        finally:
            db.close()
    if integrity != "ok":
        raise BackupError(f"The restored database failed its integrity check: {integrity}")
    conn.execute(
        "UPDATE backups SET verified_at = ? WHERE restic_snapshot_id LIKE ? || '%'", (utcnow(), latest["short_id"])
    )
    return {"snapshot": latest["short_id"], "items": items, "integrity": integrity}


def restore_to(restic: Restic, vault: Vault, snapshot_id: str, target: Path) -> Path:
    target = target.resolve()
    if vault.contains(target) or target == vault.root.resolve():
        raise BackupError("Restore into a separate folder, not into the vault.")
    if target.exists() and any(target.iterdir()):
        raise BackupError("The restore folder must be empty.")
    target.mkdir(parents=True, exist_ok=True)
    restic.restore(snapshot_id, target)
    return target
