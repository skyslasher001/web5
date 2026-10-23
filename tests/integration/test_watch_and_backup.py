"""Watched folders, the vault watching itself, and restic backups, end to end with real watchdog and restic."""

import shutil
import threading
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import keyring
import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH
from tests.support import files
from tests.support.fake_ollama import FakeOllama
from tests.support.memory_keyring import MemoryKeyring
from universe_core.app import create_app
from universe_core.settings import CoreSettings
from universe_vault.layout import Vault
from universe_vault.watch import Folder, Watcher
from universe_vault.worker import EventSink, build_context, drain

BASE = "http://127.0.0.1:47999"
RESTIC = shutil.which("restic")


def wait_for(predicate: Callable[[], Any], timeout: float = 15.0, interval: float = 0.1) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("timed out waiting")


# ---------- the watcher on its own ----------


def test_watcher_debounces_filters_and_reports(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "vault")
    vault.ensure()
    watched = tmp_path / "downloads"
    watched.mkdir()
    calls: list[tuple[str, dict[str, Any]]] = []
    lock = threading.Lock()

    def enqueue(kind: str, payload: dict[str, Any]) -> None:
        with lock:
            calls.append((kind, payload))

    watcher = Watcher(vault, enqueue, debounce_s=0.4)
    watcher.start()
    try:
        watcher.set_folders([Folder("f1", watched, exclude=("*.iso",), project_id="p1")])
        (watched / "report.pdf").write_bytes(b"%PDF-1.4 fake")
        (watched / "big.iso").write_bytes(b"x")  # excluded by the folder's globs
        (watched / "partial.crdownload").write_bytes(b"x")  # a browser download in progress
        imports = wait_for(lambda: [p for k, p in calls if k == "import"])
        assert [Path(p["path"]).name for p in imports] == ["report.pdf"]
        assert imports[0]["folder_id"] == "f1" and imports[0]["project_ids"] == ["p1"]

        note = vault.root / "notes" / "a.md"
        note.parent.mkdir(parents=True)
        note.write_text("hello")
        wait_for(lambda: any(k == "vault_file" and p["event"] == "changed" for k, p in calls))
        note.unlink()
        wait_for(lambda: any(k == "vault_file" and p["event"] == "deleted" for k, p in calls))
        (vault.index / "universe.db-wal").write_bytes(b"ignored")  # the index never triggers anything
        time.sleep(0.8)
        assert not any("universe.db" in p["path"] for _, p in calls)

        watcher.set_folders([])  # unwatch
        (watched / "later.txt").write_text("not imported")
        time.sleep(0.8)
        assert not any(Path(p["path"]).name == "later.txt" for _, p in calls)
    finally:
        watcher.stop()


# ---------- through Core ----------


class Rig:
    def __init__(self, client: TestClient, settings: CoreSettings, ollama_url: str) -> None:
        self.client = client
        token = client.app.state.ctx.internal_token  # type: ignore[attr-defined]

        def post(events: list[dict[str, Any]]) -> None:
            client.post(
                "/api/v1/internal/events", json={"events": events}, headers={"Authorization": f"Bearer {token}"}
            )

        self.ctx = build_context(
            Vault(settings.vault_dir), worker_id="t", ollama_url=ollama_url, sink=EventSink(post=post)
        )

    def drain(self) -> int:
        return drain(self.ctx)

    def items(self, **params: Any) -> list[dict[str, Any]]:
        return self.client.get("/api/v1/items", params=params, headers=AUTH).json()["items"]

    def jobs(self, kind: str) -> list[dict[str, Any]]:
        return self.client.get("/api/v1/jobs", params={"kind": kind, "status": "queued"}, headers=AUTH).json()


@pytest.fixture
def rig(make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama) -> Iterator[Rig]:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as client:
        r = Rig(client, settings, fake_ollama.url)
        yield r
        r.ctx.conn.close()


def test_watched_folder_imports_new_and_changed_files(rig: Rig, tmp_path: Path) -> None:
    folder = tmp_path / "phone-sync"
    folder.mkdir()
    files.write_photo(folder / "IMG_1.jpg")
    project = rig.client.get("/api/v1/projects", headers=AUTH).json()[1]["id"]
    created = rig.client.post(
        "/api/v1/watched-folders", json={"path": str(folder), "default_project_id": project}, headers=AUTH
    )
    assert created.status_code == 201, created.text
    assert rig.client.post("/api/v1/watched-folders", json={"path": str(folder)}, headers=AUTH).status_code == 409
    vault_dir = Path(rig.client.get("/api/v1/system/vault", headers=AUTH).json()["root"])
    (vault_dir / "notes").mkdir(exist_ok=True)
    inside = rig.client.post("/api/v1/watched-folders", json={"path": str(vault_dir / "notes")}, headers=AUTH)
    assert inside.status_code == 400 and "inside the vault" in inside.json()["detail"]
    rig.drain()  # the initial scan
    assert [(i["title"], i["project_ids"]) for i in rig.items()] == [("IMG_1", [project])]

    (folder / "trip.txt").write_text("Packing list for the lake trip", encoding="utf-8")
    wait_for(lambda: rig.jobs("import"))
    rig.drain()
    assert {i["title"] for i in rig.items()} == {"IMG_1", "trip"}

    (folder / "trip.txt").write_text("Packing list for the lake trip, plus a tent", encoding="utf-8")
    wait_for(lambda: rig.jobs("import"))
    rig.drain()
    trip = next(i for i in rig.items() if i["title"] == "trip")
    detail = rig.client.get(f"/api/v1/items/{trip['id']}", headers=AUTH).json()
    assert [v["n"] for v in detail["versions"]] == [1, 2] and detail["versions"][1]["note"] == "source changed"
    hits = rig.client.get("/api/v1/search", params={"q": "tent", "mode": "keyword"}, headers=AUTH).json()["hits"]
    assert [h["item"]["title"] for h in hits] == ["trip"]

    (folder / "trip.txt").unlink()  # deleting the source never deletes the vault copy
    time.sleep(2.5)
    rig.drain()
    assert {i["title"] for i in rig.items()} == {"IMG_1", "trip"}

    folder_id = created.json()["id"]
    assert (
        rig.client.patch(f"/api/v1/watched-folders/{folder_id}", json={"enabled": False}, headers=AUTH).json()[
            "enabled"
        ]
        is False
    )
    assert rig.client.delete(f"/api/v1/watched-folders/{folder_id}", headers=AUTH).status_code == 200
    assert rig.client.get("/api/v1/watched-folders", headers=AUTH).json() == []


def test_the_vault_watches_itself(rig: Rig) -> None:
    created = rig.client.post("/api/v1/capture", json={"text": "Draft: lake cabin budget"}, headers=AUTH).json()
    rig.drain()
    item = rig.client.get(f"/api/v1/items/{created['item_id']}", headers=AUTH).json()
    vault_dir = Path(rig.client.get("/api/v1/system/vault", headers=AUTH).json()["root"])
    note = vault_dir / item["path"]
    note.write_text(note.read_text(encoding="utf-8").replace("Draft", "Final"), encoding="utf-8")  # e.g. Obsidian
    wait_for(lambda: rig.jobs("vault_file"))
    rig.drain()
    item = rig.client.get(f"/api/v1/items/{created['item_id']}", headers=AUTH).json()
    assert item["current_version"] == 2 and len(item["versions"]) == 2

    adopted = vault_dir / "documents" / "hand-placed.txt"
    adopted.parent.mkdir(parents=True, exist_ok=True)
    adopted.write_text("Put here by hand in Explorer", encoding="utf-8")
    wait_for(lambda: rig.jobs("vault_file"))
    rig.drain()
    hand = next(i for i in rig.items() if i["title"] == "hand-placed")
    assert hand["path"] == "documents/hand-placed.txt"  # adopted in place, not copied

    adopted.unlink()
    wait_for(lambda: rig.jobs("vault_file"))
    rig.drain()
    assert all(i["title"] != "hand-placed" for i in rig.items())
    trashed = rig.items(trashed=True)
    assert [i["title"] for i in trashed] == ["hand-placed"]
    restore = rig.client.post(f"/api/v1/items/{hand['id']}/restore", headers=AUTH)
    assert restore.status_code == 409 and "deleted outside" in restore.json()["detail"]


# ---------- backups (real restic) ----------


@pytest.fixture
def memory_keyring() -> Iterator[MemoryKeyring]:
    previous = keyring.get_keyring()
    backend = MemoryKeyring()
    keyring.set_keyring(backend)
    yield backend
    keyring.set_keyring(previous)


@pytest.mark.slow
@pytest.mark.skipif(not RESTIC, reason="restic is not installed")
def test_backup_restore_and_verify_with_restic(rig: Rig, tmp_path: Path, memory_keyring: MemoryKeyring) -> None:
    c = rig.client
    status = c.get("/api/v1/backups/status", headers=AUTH).json()
    assert not status["configured"] and status["restic_found"]
    assert c.post("/api/v1/backups/run", headers=AUTH).status_code == 409

    files.write_pdf(tmp_path / "deed.pdf", ["Warranty deed for parcel 4471"])
    c.post("/api/v1/ingest/paths", json={"paths": [str(tmp_path / "deed.pdf")]}, headers=AUTH)
    rig.drain()

    repo = tmp_path / "external-drive" / "universe-backup"
    password = "correct horse battery staple"
    short = c.put("/api/v1/backups/config", json={"target": str(repo), "password": "short"}, headers=AUTH)
    assert short.status_code == 422  # a real password, please
    # Scheduled at midnight, so today's slot has always started: the scheduler is live during the whole test.
    configured = c.put(
        "/api/v1/backups/config", json={"target": str(repo), "password": password, "schedule_hour": 0}, headers=AUTH
    )
    assert configured.status_code == 200, configured.text
    assert configured.json()["configured"] and configured.json()["password_stored"]
    assert password in memory_keyring.store.values()

    assert c.post("/api/v1/backups/run", headers=AUTH).json()["started"]
    done = wait_for(
        lambda: (s := c.get("/api/v1/backups/status", headers=AUTH).json())["last_success"] and not s["running"] and s,
        timeout=60,
    )
    assert done["last_success"]["restic_snapshot_id"]
    snapshots = c.get("/api/v1/backups/snapshots", headers=AUTH).json()
    assert len(snapshots) == 1
    # Regression: the backup you just ran covers today's slot. The scheduler used to count only scheduled
    # backups, start another one right away, and make verify below find a backup still running.
    service = c.app.state.ctx.backups  # type: ignore[attr-defined]
    now = datetime.now().astimezone()
    assert not service._due(rig.ctx.conn, now)
    assert service._due(rig.ctx.conn, (now + timedelta(days=1)).replace(hour=0, minute=30))

    assert c.post("/api/v1/backups/verify", headers=AUTH).json()["started"]
    wait_for(lambda: c.get("/api/v1/backups", headers=AUTH).json()[0]["verified_at"], timeout=60)

    vault_dir = Path(c.get("/api/v1/system/vault", headers=AUTH).json()["root"])
    target = tmp_path / "restored"
    assert c.post(
        "/api/v1/backups/restore", json={"snapshot_id": snapshots[0]["short_id"], "target": str(target)}, headers=AUTH
    ).json()["started"]
    restored_pdf = wait_for(lambda: next(target.rglob("deed.pdf"), None), timeout=60)
    original = next(vault_dir.rglob("deed.pdf"))
    assert restored_pdf.read_bytes() == original.read_bytes()
    assert next(target.rglob("backup-staging/universe.db"), None) is not None  # consistent DB copy
    assert next(target.rglob(".universe/universe.db"), None) is None  # never the live file

    # Files appear while restic is still writing; the restore is done when it says so (no race on the events).
    def backup_events() -> list[str]:
        page = c.get("/api/v1/events", params={"type": "backup.*"}, headers=AUTH).json()
        return [e["type"] for e in page["events"]]

    wait_for(lambda: "backup.restored" in backup_events(), timeout=60)
    assert backup_events() == ["backup.completed", "backup.restore_tested", "backup.restored"]

    # Restoring into the vault is refused; so is a wrong password for an existing repository.
    c.post(
        "/api/v1/backups/restore",
        json={"snapshot_id": snapshots[0]["short_id"], "target": str(vault_dir / "x")},
        headers=AUTH,
    )
    wait_for(
        lambda: (
            "backup.failed"
            in [e["type"] for e in c.get("/api/v1/events", params={"type": "backup.*"}, headers=AUTH).json()["events"]]
        )
    )
    wrong = c.put(
        "/api/v1/backups/config", json={"target": str(repo), "password": "not the right password"}, headers=AUTH
    )
    assert wrong.status_code == 400 and "password" in wrong.json()["detail"]


# ---------- review 2026-10-22: regressions ----------


def test_a_backup_cut_off_by_a_restart_is_marked_failed(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama
) -> None:
    """A backup left 'running' by a crash or shutdown stayed running forever and counted as today's backup."""
    import json

    from universe_common.timeutil import utcnow

    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as c:
        conn = c.app.state.ctx.dbs.universe  # type: ignore[attr-defined]
        config = {"target": "/backups/universe", "enabled": True, "schedule_hour": 0}
        conn.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('backup.config', ?, ?)",
            (json.dumps(config), utcnow()),
        )
        conn.execute(
            "INSERT INTO backups (id, kind, target, status, started_at) VALUES ('cut-off', 'manual', ?, 'running', ?)",
            (config["target"], utcnow()),
        )
    with TestClient(create_app(settings), base_url=BASE) as c:
        ctx = c.app.state.ctx  # type: ignore[attr-defined]
        [row] = c.get("/api/v1/backups", headers=AUTH).json()
        assert row["status"] == "failed" and "interrupted" in (row["error"] or "") and row["finished_at"]
        assert ctx.backups._due(ctx.dbs.universe, datetime.now().astimezone())  # today's backup is still due
