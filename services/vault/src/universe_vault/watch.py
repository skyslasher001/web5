"""Watched folders and the vault itself (watchdog: ReadDirectoryChangesW on Windows, inotify on Linux).

- A watched folder (Downloads, a phone-sync folder…): new or changed files are imported (copied) once
  they stop changing. Deleting a file there never touches the vault copy.
- The vault: a note edited in Obsidian becomes a new version; a file you drop into the vault folder by
  hand is adopted in place; a file deleted outside the app moves its item to the trash.

Events only queue jobs; the work happens in the pipeline workers.
"""

import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from universe_common.log import get_logger
from universe_vault.ingest import DEFAULT_EXCLUDES, excluded
from universe_vault.layout import SIDECAR_SUFFIX, Vault

log = get_logger(__name__)
DEBOUNCE_S = 2.0
VAULT = "vault"


@dataclass(frozen=True)
class Folder:
    id: str
    path: Path
    recursive: bool = True
    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    project_id: str | None = None


@dataclass
class _Pending:
    folder_id: str
    first_seen: float
    last_event: float
    size: int = -1


Enqueue = Callable[[str, dict[str, Any]], None]


class _Handler(FileSystemEventHandler):
    def __init__(self, watcher: "Watcher", folder_id: str) -> None:
        self.watcher = watcher
        self.folder_id = folder_id

    def on_created(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.touch(Path(os.fsdecode(event.src_path)), self.folder_id)

    def on_modified(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            self.watcher.touch(Path(os.fsdecode(event.src_path)), self.folder_id)

    def on_moved(self, event: FileSystemEvent) -> None:
        if not event.is_directory:
            src, dest = Path(os.fsdecode(event.src_path)), Path(os.fsdecode(event.dest_path))
            if self.folder_id == VAULT:
                self.watcher.moved(src, dest)
            else:
                self.watcher.touch(dest, self.folder_id)

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not event.is_directory and self.folder_id == VAULT:
            self.watcher.deleted(Path(os.fsdecode(event.src_path)))


@dataclass
class Watcher:
    vault: Vault
    enqueue: Enqueue
    debounce_s: float = DEBOUNCE_S
    watch_vault: bool = True
    _observer: Any = None
    _folders: dict[str, Folder] = field(default_factory=dict)
    _watches: dict[str, Any] = field(default_factory=dict)
    _pending: dict[Path, _Pending] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _stop: threading.Event = field(default_factory=threading.Event)
    _thread: threading.Thread | None = None

    def start(self) -> None:
        self._observer = Observer()
        if self.watch_vault:
            self._watches[VAULT] = self._observer.schedule(_Handler(self, VAULT), str(self.vault.root), recursive=True)
        self._observer.start()
        self._thread = threading.Thread(target=self._settle_loop, name="watch-debounce", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._observer is not None:
            self._observer.stop()
            self._observer.join(timeout=5)
        if self._thread is not None:
            self._thread.join(timeout=5)

    def set_folders(self, folders: list[Folder]) -> None:
        """Watch exactly these folders (call after any add, change or removal)."""
        wanted = {f.id: f for f in folders}
        for folder_id in [fid for fid in self._watches if fid != VAULT and fid not in wanted]:
            self._observer.unschedule(self._watches.pop(folder_id))
            self._folders.pop(folder_id, None)
        for folder in folders:
            current = self._folders.get(folder.id)
            if current == folder and folder.id in self._watches:
                continue
            if folder.id in self._watches:
                self._observer.unschedule(self._watches.pop(folder.id))
            try:
                self._watches[folder.id] = self._observer.schedule(
                    _Handler(self, folder.id), str(folder.path), recursive=folder.recursive
                )
                self._folders[folder.id] = folder
            except OSError as exc:
                log.warning("watch_failed", folder=str(folder.path), error=str(exc))

    # ---------- events → pending → jobs ----------

    def _wanted(self, path: Path, folder_id: str) -> bool:
        if path.name.endswith((SIDECAR_SUFFIX, ".part", ".tmp")) or path.name.startswith("."):
            return False
        if folder_id == VAULT:
            return not self.vault.in_index(path)
        folder = self._folders.get(folder_id)
        if folder is None or self.vault.contains(path):
            return False
        try:
            relative = path.relative_to(folder.path)
        except ValueError:
            return False
        if excluded(relative, (*DEFAULT_EXCLUDES, *folder.exclude)):
            return False
        return not folder.include or any(relative.match(p) for p in folder.include)

    def touch(self, path: Path, folder_id: str) -> None:
        if not self._wanted(path, folder_id):
            return
        now = time.monotonic()
        with self._lock:
            entry = self._pending.get(path)
            if entry is None:
                self._pending[path] = _Pending(folder_id, now, now)
            else:
                entry.last_event = now

    def deleted(self, path: Path) -> None:
        if self.vault.in_index(path) or path.name.endswith(SIDECAR_SUFFIX):
            return
        with self._lock:
            self._pending.pop(path, None)
        self._safe_enqueue("vault_file", {"path": str(path), "event": "deleted"})

    def moved(self, src: Path, dest: Path) -> None:
        """A rename or move inside the vault. A rename is atomic (the file is complete), so it isn't debounced;
        the worker keeps the item if the bytes are the same (`ingest.moved_inside`)."""
        if not self.vault.contains(dest) or not self._wanted(dest, VAULT):
            self.deleted(src)  # moved out of the vault, into the index or to a temporary name
            return
        if not self._wanted(src, VAULT):  # a temporary file put in place (a safe save, an import): just a change
            self.touch(dest, VAULT)
            return
        with self._lock:
            self._pending.pop(src, None)
            self._pending.pop(dest, None)
        self._safe_enqueue("vault_file", {"path": str(dest), "event": "moved", "from": str(src)})

    def _settle_loop(self) -> None:
        while not self._stop.wait(0.5):
            self.settle()

    def settle(self, *, now: float | None = None) -> int:
        """Queue files that have been quiet for `debounce_s` and whose size stopped changing."""
        now = time.monotonic() if now is None else now
        ready: list[tuple[Path, str]] = []
        with self._lock:
            for path, entry in list(self._pending.items()):
                if now - entry.last_event < self.debounce_s:
                    continue
                try:
                    size = path.stat().st_size
                except OSError:
                    del self._pending[path]  # gone again (a temp file)
                    continue
                if size != entry.size:
                    entry.size, entry.last_event = size, now  # still being written: wait one more round
                    continue
                del self._pending[path]
                ready.append((path, entry.folder_id))
        for path, folder_id in ready:
            if folder_id == VAULT:
                self._safe_enqueue("vault_file", {"path": str(path), "event": "changed"})
            else:
                folder = self._folders.get(folder_id)
                self._safe_enqueue(
                    "import",
                    {
                        "path": str(path),
                        "origin": str(path),
                        "folder_id": folder_id,
                        "project_ids": [folder.project_id] if folder and folder.project_id else [],
                        "interactive": False,
                    },
                )
        return len(ready)

    def _safe_enqueue(self, kind: str, payload: dict[str, Any]) -> None:
        try:
            self.enqueue(kind, payload)
        except Exception:
            log.exception("watch_enqueue_failed", kind=kind, path=payload.get("path"))
