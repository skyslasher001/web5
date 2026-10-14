"""Item rows: create, read, list, pipeline stage status, chunks and the title/metadata indexes.

Plain functions over a `sqlite3.Connection`, so Core (event loop or threads), workers and tests all
use the same SQL. Callers own transactions.
"""

import base64
import json
import sqlite3
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from universe_common.ids import uuid7
from universe_common.timeutil import utcnow
from universe_vault import links
from universe_vault.layout import Vault
from universe_vault.schemas import Item, ItemPage, ItemSource, ItemStage, ItemSummary, ItemVersion

# Stages a finished item can't be "done" without, unless skipped.
_ITEM_COLUMNS = (
    "id, type, title, status, path, mime, size_bytes, captured_at, created_at, updated_at, pinned, open_count,"
    " last_opened_at, pipeline_status, trashed_at"
)
SORTS = {
    "added": ("created_at", "DESC"),
    "captured": ("captured_at", "DESC"),
    "opened": ("COALESCE(last_opened_at, '')", "DESC"),
    "title": ("title COLLATE NOCASE", "ASC"),
}
MAX_META_TEXT = 4000


@dataclass(frozen=True)
class ChunkIn:
    text: str
    kind: str = "text"
    page: int | None = None
    char_start: int | None = None
    char_end: int | None = None


@dataclass
class ItemFilters:
    types: Sequence[str] = ()
    project_id: str | None = None
    tag: str | None = None
    status: str | None = None
    date_from: str | None = None
    date_to: str | None = None
    pipeline_status: str | None = None
    pinned: bool | None = None
    trashed: bool = False


def create_source(conn: sqlite3.Connection, kind: str, origin: str | None = None, **extra: Any) -> str:
    source_id = uuid7()
    conn.execute(
        "INSERT INTO sources (id, kind, origin, api_key_id, extra, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (source_id, kind, origin, extra.pop("api_key_id", None), json.dumps(extra), utcnow()),
    )
    return source_id


def get_row(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()


def find_by_hash(conn: sqlite3.Connection, content_hash: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM items WHERE content_hash = ? AND trashed_at IS NULL ORDER BY created_at LIMIT 1",
        (content_hash,),
    ).fetchone()


def find_by_path(conn: sqlite3.Connection, rel_path: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM items WHERE path = ?", (rel_path,)).fetchone()


def add_to_projects(conn: sqlite3.Connection, item_id: str, project_ids: Iterable[str], actor: str) -> list[str]:
    added = []
    for project_id in dict.fromkeys(project_ids):
        if not conn.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO item_projects (item_id, project_id, added_by, added_at) VALUES (?, ?, ?, ?)",
            (item_id, project_id, actor, utcnow()),
        )
        if cursor.rowcount:
            added.append(project_id)
    if added:
        touch(conn, item_id)
    return added


def remove_from_project(conn: sqlite3.Connection, item_id: str, project_id: str) -> bool:
    cursor = conn.execute("DELETE FROM item_projects WHERE item_id = ? AND project_id = ?", (item_id, project_id))
    if cursor.rowcount:
        touch(conn, item_id)
    return bool(cursor.rowcount)


def touch(conn: sqlite3.Connection, item_id: str) -> None:
    """Mark an item changed (its galaxies, say), so the universe view's incremental refresh picks it up."""
    conn.execute("UPDATE items SET updated_at = ? WHERE id = ?", (utcnow(), item_id))


def set_tags(conn: sqlite3.Connection, item_id: str, names: Iterable[str], actor: str) -> list[str]:
    """Replace the item's confirmed tags with `names` (suggested tags are left alone)."""
    wanted = {n.strip(): None for n in names if n.strip()}
    conn.execute("DELETE FROM item_tags WHERE item_id = ? AND state = 'confirmed'", (item_id,))
    for name in wanted:
        row = conn.execute("SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)).fetchone()
        tag_id = row["id"] if row else uuid7()
        if row is None:
            conn.execute("INSERT INTO tags (id, name, created_at) VALUES (?, ?, ?)", (tag_id, name, utcnow()))
        conn.execute(
            "INSERT OR REPLACE INTO item_tags (item_id, tag_id, state, source, created_at)"
            " VALUES (?, ?, 'confirmed', ?, ?)",
            (item_id, tag_id, actor, utcnow()),
        )
    return list(wanted)


# ---------- pipeline stages ----------


def set_stage(
    conn: sqlite3.Connection,
    item_id: str,
    stage: str,
    status: str,
    *,
    model: str | None = None,
    model_version: str | None = None,
    error: str | None = None,
    detail: str | None = None,
    count_attempt: bool = False,
) -> None:
    conn.execute(
        "INSERT INTO item_stages (item_id, stage, status, model, model_version, attempts, error, detail, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (item_id, stage) DO UPDATE SET status = excluded.status,"
        " model = COALESCE(excluded.model, model), model_version = COALESCE(excluded.model_version, model_version),"
        " attempts = attempts + excluded.attempts, error = excluded.error, detail = excluded.detail,"
        " updated_at = excluded.updated_at",
        (item_id, stage, status, model, model_version, 1 if count_attempt else 0, error, detail, utcnow()),
    )


def stages(conn: sqlite3.Connection, item_id: str) -> list[ItemStage]:
    rows = conn.execute("SELECT * FROM item_stages WHERE item_id = ? ORDER BY rowid", (item_id,)).fetchall()
    return [ItemStage(**{k: row[k] for k in set(row.keys()) - {"item_id"}}) for row in rows]


def refresh_pipeline_status(conn: sqlite3.Connection, item_id: str) -> str:
    statuses = [row["status"] for row in conn.execute("SELECT status FROM item_stages WHERE item_id = ?", (item_id,))]
    if not statuses:
        status = "pending"
    elif "failed" in statuses:
        status = "failed"
    elif all(s in ("done", "skipped") for s in statuses):
        status = "done"
    else:
        status = "processing"
    conn.execute("UPDATE items SET pipeline_status = ? WHERE id = ?", (status, item_id))
    return status


# ---------- chunks and the title/metadata index ----------


def replace_chunks(
    conn: sqlite3.Connection, item_id: str, version_n: int, kinds: Sequence[str], chunks: Sequence[ChunkIn]
) -> list[int]:
    """Replace the item's chunks of the given kinds. Returns the new chunk ids (FTS stays in sync via triggers)."""
    marks = ",".join("?" * len(kinds))
    conn.execute(f"DELETE FROM chunks WHERE item_id = ? AND kind IN ({marks})", (item_id, *kinds))  # noqa: S608
    start = conn.execute("SELECT COALESCE(MAX(ord), -1) + 1 FROM chunks WHERE item_id = ?", (item_id,)).fetchone()[0]
    ids = []
    for offset, chunk in enumerate(chunks):
        cursor = conn.execute(
            "INSERT INTO chunks (item_id, version_n, ord, kind, text, page, char_start, char_end, token_count)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                item_id,
                version_n,
                start + offset,
                chunk.kind,
                chunk.text,
                chunk.page,
                chunk.char_start,
                chunk.char_end,
                max(1, len(chunk.text) // 4),
            ),
        )
        ids.append(int(cursor.lastrowid or 0))
    return ids


def item_chunks(conn: sqlite3.Connection, item_id: str) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM chunks WHERE item_id = ? ORDER BY ord", (item_id,)).fetchall()


def _meta_text(metadata: dict[str, Any], path: str) -> str:
    parts = [path.rsplit("/", 1)[-1]]
    for key in ("artist", "album", "albumartist", "composer", "genre", "camera", "lens", "author", "subject", "url"):
        value = metadata.get(key)
        if value:
            parts.append(str(value))
    for key in ("keywords", "sheets"):
        value = metadata.get(key)
        if isinstance(value, list):
            parts.extend(str(v) for v in value)
    return " ".join(parts)[:MAX_META_TEXT]


def reindex_item(conn: sqlite3.Connection, item_id: str) -> None:
    """Rewrite the item's rows in the title/metadata FTS indexes (also call after tag or title changes)."""
    conn.execute("DELETE FROM items_fts WHERE item_id = ?", (item_id,))
    conn.execute("DELETE FROM items_trigram WHERE item_id = ?", (item_id,))
    row = get_row(conn, item_id)
    if row is None:
        return
    if row["trashed_at"] is not None:
        links.unresolve(conn, item_id)  # wikilinks to it wait for it again
        return
    tags = " ".join(
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id WHERE it.item_id = ?", (item_id,)
        )
    )
    meta = _meta_text(json.loads(row["metadata"] or "{}"), row["path"])
    conn.execute(
        "INSERT INTO items_fts (item_id, title, tags, meta) VALUES (?, ?, ?, ?)", (item_id, row["title"], tags, meta)
    )
    conn.execute(
        "INSERT INTO items_trigram (item_id, title) VALUES (?, ?)",
        (item_id, f"{row['title']} {row['path'].rsplit('/', 1)[-1]}"),
    )
    links.resolve_pending(conn, item_id, row["title"])


# ---------- reading items for the API ----------


def _projects_and_tags(
    conn: sqlite3.Connection, ids: Sequence[str]
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    projects: dict[str, list[str]] = {i: [] for i in ids}
    tags: dict[str, list[str]] = {i: [] for i in ids}
    if not ids:
        return projects, tags
    marks = ",".join("?" * len(ids))
    for row in conn.execute(
        f"SELECT item_id, project_id FROM item_projects WHERE item_id IN ({marks}) ORDER BY added_at",  # noqa: S608
        tuple(ids),
    ):
        projects[row["item_id"]].append(row["project_id"])
    for row in conn.execute(
        f"SELECT it.item_id, t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id"  # noqa: S608
        f" WHERE it.item_id IN ({marks}) AND it.state = 'confirmed' ORDER BY t.name",
        tuple(ids),
    ):
        tags[row["item_id"]].append(row["name"])
    return projects, tags


def summaries(conn: sqlite3.Connection, vault: Vault, rows: Sequence[sqlite3.Row]) -> list[ItemSummary]:
    ids = [row["id"] for row in rows]
    projects, tags = _projects_and_tags(conn, ids)
    return [
        ItemSummary(
            id=row["id"],
            type=row["type"],
            title=row["title"],
            status=row["status"],
            path=row["path"],
            mime=row["mime"],
            size_bytes=row["size_bytes"],
            captured_at=row["captured_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            pinned=bool(row["pinned"]),
            open_count=row["open_count"],
            last_opened_at=row["last_opened_at"],
            pipeline_status=row["pipeline_status"],
            has_thumbnail=vault.thumb_path(row["id"]).exists(),
            project_ids=projects[row["id"]],
            tags=tags[row["id"]],
            trashed_at=row["trashed_at"],
        )
        for row in rows
    ]


def summaries_by_id(conn: sqlite3.Connection, vault: Vault, ids: Sequence[str]) -> dict[str, ItemSummary]:
    if not ids:
        return {}
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"SELECT {_ITEM_COLUMNS} FROM items WHERE id IN ({marks})", tuple(ids)).fetchall()  # noqa: S608
    return {s.id: s for s in summaries(conn, vault, rows)}


def get_item(conn: sqlite3.Connection, vault: Vault, item_id: str) -> Item | None:
    row = get_row(conn, item_id)
    if row is None:
        return None
    summary = summaries(conn, vault, [row])[0]
    source = None
    if row["source_id"]:
        src = conn.execute("SELECT kind, origin, created_at FROM sources WHERE id = ?", (row["source_id"],)).fetchone()
        if src:
            source = ItemSource(kind=src["kind"], origin=src["origin"], created_at=src["created_at"])
    versions = [
        ItemVersion(
            n=v["n"],
            content_hash=v["content_hash"],
            size_bytes=v["size_bytes"],
            created_by=v["created_by"],
            note=v["note"],
            created_at=v["created_at"],
        )
        for v in conn.execute("SELECT * FROM versions WHERE item_id = ? ORDER BY n", (item_id,))
    ]
    return Item(
        **summary.model_dump(),
        metadata=json.loads(row["metadata"] or "{}"),
        summary=row["summary"],
        current_version=row["current_version"],
        content_hash=row["content_hash"],
        source=source,
        stages=stages(conn, item_id),
        versions=versions,
    )


def filter_sql(filters: ItemFilters, alias: str = "i") -> tuple[str, list[Any]]:
    """WHERE fragments for item filters, shared by listing and search."""
    clauses = [f"{alias}.trashed_at IS {'NOT ' if filters.trashed else ''}NULL"]
    params: list[Any] = []
    if filters.types:
        clauses.append(f"{alias}.type IN ({','.join('?' * len(filters.types))})")
        params.extend(filters.types)
    if filters.project_id:
        clauses.append(f"{alias}.id IN (SELECT item_id FROM item_projects WHERE project_id = ?)")  # noqa: S608
        params.append(filters.project_id)
    if filters.tag:
        clauses.append(
            f"{alias}.id IN (SELECT it.item_id FROM item_tags it JOIN tags t ON t.id = it.tag_id"  # noqa: S608
            " WHERE t.name = ? COLLATE NOCASE)"
        )
        params.append(filters.tag)
    if filters.status:
        clauses.append(f"{alias}.status = ?")
        params.append(filters.status)
    if filters.pipeline_status:
        clauses.append(f"{alias}.pipeline_status = ?")
        params.append(filters.pipeline_status)
    if filters.date_from:
        clauses.append(f"{alias}.captured_at >= ?")
        params.append(filters.date_from)
    if filters.date_to:
        clauses.append(f"{alias}.captured_at < ?")
        params.append(filters.date_to)
    if filters.pinned is not None:
        clauses.append(f"{alias}.pinned = ?")
        params.append(1 if filters.pinned else 0)
    return " AND ".join(clauses), params


def _encode_cursor(value: Any, item_id: str) -> str:
    return base64.urlsafe_b64encode(json.dumps([value, item_id]).encode()).decode()


def _decode_cursor(cursor: str) -> tuple[Any, str]:
    value, item_id = json.loads(base64.urlsafe_b64decode(cursor.encode()))
    return value, str(item_id)


def list_items(
    conn: sqlite3.Connection,
    vault: Vault,
    filters: ItemFilters,
    *,
    sort: str = "added",
    cursor: str | None = None,
    limit: int = 100,
) -> ItemPage:
    column, direction = SORTS.get(sort, SORTS["added"])
    where, params = filter_sql(filters)
    total = None
    if not cursor:
        total = conn.execute(f"SELECT COUNT(*) FROM items i WHERE {where}", params).fetchone()[0]  # noqa: S608
    if cursor:
        value, last_id = _decode_cursor(cursor)
        op = "<" if direction == "DESC" else ">"
        where += f" AND ({column} {op} ? OR ({column} = ? AND i.id {op} ?))"
        params.extend([value, value, last_id])
    limit = max(1, min(limit, 500))
    rows = conn.execute(
        f"SELECT {_ITEM_COLUMNS}, {column} AS sort_value FROM items i WHERE {where}"  # noqa: S608
        f" ORDER BY {column} {direction}, i.id {direction} LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = _encode_cursor(rows[-1]["sort_value"], rows[-1]["id"]) if more and rows else None
    return ItemPage(items=summaries(conn, vault, rows), next_cursor=next_cursor, total=total)
