"""Trash and real deletion (SPEC §3.5: originals, embeddings, caches and thumbnails all go).

Trash moves the file into `.universe/trash/<id>/` and hides the item. Restore puts it back. Purge
deletes the file, every version, the sidecar, the thumbnail, chunks and their FTS rows, vectors in every
LanceDB table, jobs and source records. Restic snapshots keep old data until they're pruned.
"""

import json
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow
from universe_vault import store
from universe_vault.jobs import iso, now_dt
from universe_vault.layout import Vault, sidecar_path
from universe_vault.vectors import VectorStore

TRASH_DAYS = 30


class PurgeError(RuntimeError):
    pass


def _move(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))  # a rename: the trash is inside the vault, on the same drive


def trash(conn: sqlite3.Connection, vault: Vault, item_id: str) -> bool:
    row = store.get_row(conn, item_id)
    if row is None or row["trashed_at"] is not None:
        return False
    original = vault.abs(row["path"])
    dest = vault.trash / item_id / original.name
    if original.exists():
        _move(original, dest)
    side = sidecar_path(original)
    if side.exists():
        _move(side, dest.with_name(dest.name + ".universe.json"))
    with transaction(conn):
        conn.execute(
            "UPDATE items SET trashed_at = ?, path = ?, metadata = json_set(metadata, '$.trashed_from', ?),"
            " updated_at = ? WHERE id = ?",
            (utcnow(), vault.rel(dest), row["path"], utcnow(), item_id),
        )
        conn.execute("UPDATE jobs SET status = 'cancelled', idempotency_key = NULL, finished_at = ? WHERE item_id = ?"
                     " AND status = 'queued'", (utcnow(), item_id))  # fmt: skip
        store.reindex_item(conn, item_id)  # removes it from the title indexes
    return True


def restore(conn: sqlite3.Connection, vault: Vault, item_id: str) -> bool:
    row = store.get_row(conn, item_id)
    if row is None or row["trashed_at"] is None:
        return False
    meta = json.loads(row["metadata"] or "{}")
    original_rel = meta.pop("trashed_from", None)
    current = vault.abs(row["path"])
    target = vault.abs(original_rel) if original_rel else vault.root / "files" / current.name
    if target.exists():
        target = vault.free_path(target.parent, target.name)
    if current.exists():
        _move(current, target)
    side = current.with_name(current.name + ".universe.json")
    if side.exists():
        _move(side, sidecar_path(target))
    shutil.rmtree(vault.trash / item_id, ignore_errors=True)
    with transaction(conn):
        conn.execute(
            "UPDATE items SET trashed_at = NULL, path = ?, metadata = ?, updated_at = ? WHERE id = ?",
            (vault.rel(target), json.dumps(meta), utcnow(), item_id),
        )
        store.reindex_item(conn, item_id)
    return True


def purge(conn: sqlite3.Connection, vault: Vault, vectors: VectorStore, item_id: str) -> bool:
    """Delete an item everywhere. Returns False if it didn't exist."""
    row = store.get_row(conn, item_id)
    if row is None:
        return False
    original = vault.abs(row["path"])
    version_paths = [
        vault.abs(r["path"]) for r in conn.execute("SELECT path FROM versions WHERE item_id = ?", (item_id,))
    ]
    vectors.delete_item(item_id)
    for path in {original, sidecar_path(original), vault.thumb_path(item_id), *version_paths}:
        if path.exists() and path.is_file():
            path.unlink()
    for directory in (vault.version_dir(item_id), vault.trash / item_id):
        shutil.rmtree(directory, ignore_errors=True)
    with transaction(conn):
        conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
        conn.execute("DELETE FROM items_trigram WHERE item_id = ?", (item_id,))
        conn.execute("UPDATE source_files SET item_id = NULL WHERE item_id = ?", (item_id,))
        source_id = row["source_id"]
        # Cascades to versions, stages, chunks (and their FTS rows), tags, project membership and jobs.
        conn.execute("DELETE FROM items WHERE id = ?", (item_id,))
        if source_id:
            conn.execute(
                "DELETE FROM sources WHERE id = ?"
                " AND id NOT IN (SELECT source_id FROM items WHERE source_id IS NOT NULL)",
                (source_id,),
            )
    return True


def expired_trash(conn: sqlite3.Connection, *, days: int = TRASH_DAYS) -> list[str]:
    cutoff = iso(now_dt() - timedelta(days=days))
    return [
        r["id"] for r in conn.execute("SELECT id FROM items WHERE trashed_at IS NOT NULL AND trashed_at < ?", (cutoff,))
    ]
