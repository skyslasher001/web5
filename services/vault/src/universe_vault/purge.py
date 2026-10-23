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
from universe_vault import links, store
from universe_vault.jobs import iso, now_dt
from universe_vault.layout import Vault, sha256_file, sidecar_path
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
    if not current.exists():
        raise PurgeError("The file was deleted outside the app, so there is nothing to restore.")
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


def _own_version_files(conn: sqlite3.Connection, vault: Vault, item_id: str) -> list[Path]:
    """Files of an item's earlier versions that are still its own.

    A version row can point at a path the item has left (it was trashed, or deleted outside the app) and that
    another item now uses. Its version and trash folders are deleted whole; any other version file is deleted
    only if no other item refers to that path and the file still holds that version's bytes.
    """
    own_dirs = (vault.version_dir(item_id).resolve(), (vault.trash / item_id).resolve())
    own: list[Path] = []
    rows = conn.execute("SELECT path, content_hash FROM versions WHERE item_id = ?", (item_id,)).fetchall()
    for row in rows:
        path = vault.abs(row["path"])
        if any(d in path.parents for d in own_dirs) or not path.is_file():
            continue
        shared = conn.execute(
            "SELECT 1 FROM items WHERE path = ? AND id != ?"
            " UNION ALL SELECT 1 FROM versions WHERE path = ? AND item_id != ? LIMIT 1",
            (row["path"], item_id, row["path"], item_id),
        ).fetchone()
        if shared is None and sha256_file(path) == row["content_hash"]:
            own.append(path)
    return own


def purge(conn: sqlite3.Connection, vault: Vault, vectors: VectorStore, item_id: str) -> bool:
    """Delete an item everywhere. Returns False if it didn't exist."""
    row = store.get_row(conn, item_id)
    if row is None:
        return False
    original = vault.abs(row["path"])
    version_paths = _own_version_files(conn, vault, item_id)
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
        links.unresolve(conn, item_id)  # [[links]] to it survive its deletion, waiting for a new target
        # The universe's incremental refresh learns about it here (it won't be in `items` any more).
        conn.execute("INSERT OR REPLACE INTO removed_items (id, removed_at) VALUES (?, ?)", (item_id, utcnow()))
        conn.execute("DELETE FROM removed_items WHERE removed_at < ?", (iso(now_dt() - timedelta(days=30)),))
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
