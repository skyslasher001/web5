"""`<file>.universe.json` sidecars: a readable mirror of what the app knows about a non-note item.

The database is the source of truth for these items; the sidecar keeps the vault meaningful without
the app (and lets "rebuild index from vault" recover tags, projects and captions).
"""

import json
import os
import sqlite3
from typing import Any

from universe_vault import store
from universe_vault.layout import Vault, sidecar_path

SIDECAR_VERSION = 1
MAX_TEXT = 20_000


def build(conn: sqlite3.Connection, item_id: str) -> dict[str, Any] | None:
    row = store.get_row(conn, item_id)
    if row is None:
        return None
    meta = json.loads(row["metadata"] or "{}")
    projects = [
        r["slug"]
        for r in conn.execute(
            "SELECT p.slug FROM item_projects ip JOIN projects p ON p.id = ip.project_id WHERE ip.item_id = ?",
            (item_id,),
        )
    ]
    tags = [
        r["name"]
        for r in conn.execute(
            "SELECT t.name FROM item_tags it JOIN tags t ON t.id = it.tag_id"
            " WHERE it.item_id = ? AND it.state = 'confirmed'",
            (item_id,),
        )
    ]
    texts: dict[str, str] = {}
    for kind in ("ocr", "caption"):
        rows = conn.execute("SELECT text FROM chunks WHERE item_id = ? AND kind = ? ORDER BY ord", (item_id, kind))
        joined = "\n".join(r["text"] for r in rows)
        if joined:
            texts[kind] = joined[:MAX_TEXT]
    data: dict[str, Any] = {
        "universe_sidecar": SIDECAR_VERSION,
        "id": row["id"],
        "type": row["type"],
        "title": row["title"],
        "status": row["status"],
        "captured": row["captured_at"],
        "created": row["created_at"],
        "sha256": row["content_hash"],
        "projects": projects,
        "tags": tags,
        "pinned": bool(row["pinned"]),
        "metadata": meta,
    }
    if texts.get("caption"):
        data["caption"] = texts["caption"]
    if texts.get("ocr"):
        data["ocr_text"] = texts["ocr"]
    return data


def write(conn: sqlite3.Connection, vault: Vault, item_id: str) -> bool:
    row = store.get_row(conn, item_id)
    if row is None or row["trashed_at"] is not None:
        return False
    data = build(conn, item_id)
    if data is None:
        return False
    target = sidecar_path(vault.abs(row["path"]))
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, target)
    return True
