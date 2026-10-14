"""Links between items: the filaments in the universe, note backlinks and the graph layout (ADR-0012).

Notes link with `[[Title]]` (Obsidian style; `[[Title|label]]` and `[[Title#heading]]` work too). A link
whose target doesn't exist yet is kept by title and resolves when an item with that title appears. Wikilinks
keep their target text (`to_title`) after resolving, so when the target is trashed or deleted the link goes
back to waiting for it instead of disappearing.
Plain functions over a connection; callers own transactions.
"""

import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from universe_common.ids import uuid7
from universe_common.timeutil import utcnow

WIKILINK = re.compile(r"\[\[([^\[\]|#\n]{1,200})(?:#[^\[\]|\n]*)?(?:\|[^\[\]\n]*)?\]\]")
MAX_LINKS_PER_NOTE = 500


@dataclass(frozen=True)
class LinkRow:
    id: str
    from_id: str
    to_id: str
    kind: str
    state: str
    strength: float


def wikilink_targets(text: str) -> list[str]:
    """Distinct `[[targets]]` in a note, in order of appearance."""
    seen: dict[str, str] = {}
    for match in WIKILINK.finditer(text):
        target = match.group(1).strip()
        if target and target.lower() not in seen:
            seen[target.lower()] = target
    return list(seen.values())[:MAX_LINKS_PER_NOTE]


def resolve(conn: sqlite3.Connection, target: str) -> str | None:
    """The live item a link target names: its id, title (any case) or slug."""
    row = conn.execute(
        "SELECT id FROM items WHERE trashed_at IS NULL AND (id = ? OR title = ? COLLATE NOCASE OR slug = ?)"
        " ORDER BY id = ? DESC, created_at LIMIT 1",
        (target, target, target.lower(), target),
    ).fetchone()
    return row["id"] if row else None


def sync_wikilinks(conn: sqlite3.Connection, item_id: str, text: str) -> int:
    """Make the note's wikilink rows match its text. Returns how many links it has."""
    conn.execute("DELETE FROM links WHERE from_id = ? AND kind = 'wikilink'", (item_id,))
    now = utcnow()
    count = 0
    for target in wikilink_targets(text):
        to_id = resolve(conn, target)
        if to_id == item_id:
            continue
        conn.execute(
            "INSERT OR IGNORE INTO links (id, from_id, to_id, to_title, kind, created_by, created_at)"
            " VALUES (?, ?, ?, ?, 'wikilink', 'system', ?)",
            (uuid7(), item_id, to_id, target, now),
        )
        count += 1
    return count


def resolve_pending(conn: sqlite3.Connection, item_id: str, title: str) -> int:
    """An item with this title exists now: links that were waiting for it point to it. Matches the way
    `resolve` does: the item's id, its title (any case) or its slug."""
    slug_row = conn.execute("SELECT slug FROM items WHERE id = ?", (item_id,)).fetchone()
    slug = slug_row["slug"] if slug_row and slug_row["slug"] else title.lower()
    rows = conn.execute(
        "SELECT id, from_id FROM links WHERE to_id IS NULL AND from_id != ?"
        " AND (to_title = ? COLLATE NOCASE OR to_title = ? COLLATE NOCASE OR to_title = ?)",
        (item_id, title, slug, item_id),
    ).fetchall()
    for row in rows:
        exists = conn.execute(
            "SELECT 1 FROM links WHERE from_id = ? AND to_id = ? AND kind = 'wikilink'", (row["from_id"], item_id)
        ).fetchone()
        if exists:
            conn.execute("DELETE FROM links WHERE id = ?", (row["id"],))
        else:
            conn.execute("UPDATE links SET to_id = ? WHERE id = ?", (item_id, row["id"]))
    return len(rows)


def unresolve(conn: sqlite3.Connection, item_id: str) -> int:
    """The item was trashed or is being deleted: wikilinks to it wait for their target again (another live
    item with that name, if there is one, or the next one to appear). Manual links stay; they're hidden while
    the item is in the trash and removed with it."""
    rows = conn.execute(
        "SELECT l.id, l.from_id, COALESCE(l.to_title, i.title) AS target FROM links l"
        " JOIN items i ON i.id = l.to_id WHERE l.to_id = ? AND l.kind = 'wikilink'",
        (item_id,),
    ).fetchall()
    for row in rows:
        other = resolve(conn, row["target"])
        if other in (row["from_id"], item_id):  # never itself (a live item being deleted) or a self-link
            other = None
        taken = conn.execute(
            "SELECT 1 FROM links WHERE from_id = ? AND kind = 'wikilink' AND"
            " (to_id = ? OR (to_id IS NULL AND to_title = ? COLLATE NOCASE)) AND id != ?",
            (row["from_id"], other, row["target"], row["id"]),
        ).fetchone()
        if taken:
            conn.execute("DELETE FROM links WHERE id = ?", (row["id"],))
        else:
            conn.execute("UPDATE links SET to_id = ?, to_title = ? WHERE id = ?", (other, row["target"], row["id"]))
    return len(rows)


SEQUENCE_WINDOW_S = 120  # opening B within two minutes of A counts as moving from A to B


def record_activity(
    conn: sqlite3.Connection, from_id: str, to_id: str, *, source: str, actor: str
) -> dict[str, str | None] | None:
    """Two live items fired together (SPEC §10, neural pathways): record it for the brain layer. Returns the
    `link.fired` payload (with the link between them, if there is one), or None if nothing was recorded."""
    if from_id == to_id:
        return None
    live = conn.execute(
        "SELECT COUNT(*) FROM items WHERE id IN (?, ?) AND trashed_at IS NULL", (from_id, to_id)
    ).fetchone()[0]
    if live != 2:
        return None
    a, b = sorted((from_id, to_id))
    conn.execute(
        "INSERT INTO link_activity (id, a_id, b_id, source, actor, at) VALUES (?, ?, ?, ?, ?, ?)",
        (uuid7(), a, b, source, actor, utcnow()),
    )
    link = conn.execute(
        "SELECT id FROM links WHERE (from_id = ? AND to_id = ?) OR (from_id = ? AND to_id = ?)"
        " ORDER BY kind = 'wikilink' DESC LIMIT 1",
        (from_id, to_id, to_id, from_id),
    ).fetchone()
    return {"from_id": from_id, "to_id": to_id, "source": source, "link_id": link["id"] if link else None}


def previous_open(conn: sqlite3.Connection, item_id: str, now: str) -> str | None:
    """The item opened just before this one (within SEQUENCE_WINDOW_S), if any."""
    since = (datetime.fromisoformat(now) - timedelta(seconds=SEQUENCE_WINDOW_S)).isoformat(timespec="milliseconds")
    row = conn.execute(
        "SELECT id FROM items WHERE id != ? AND trashed_at IS NULL AND last_opened_at > ?"
        " ORDER BY last_opened_at DESC LIMIT 1",
        (item_id, since.replace("+00:00", "Z")),
    ).fetchone()
    return row["id"] if row else None


def add(conn: sqlite3.Connection, from_id: str, to_id: str, *, kind: str = "manual", actor: str = "user") -> str:
    """Link two items (idempotent). Returns the link id."""
    if from_id == to_id:
        raise ValueError("an item can't link to itself")
    for item_id in (from_id, to_id):
        if conn.execute("SELECT 1 FROM items WHERE id = ? AND trashed_at IS NULL", (item_id,)).fetchone() is None:
            raise LookupError(f"no item with id {item_id}")
    conn.execute(
        "INSERT OR IGNORE INTO links (id, from_id, to_id, kind, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (uuid7(), from_id, to_id, kind, actor, utcnow()),
    )
    row = conn.execute(
        "SELECT id FROM links WHERE from_id = ? AND to_id = ? AND kind = ?", (from_id, to_id, kind)
    ).fetchone()
    return str(row["id"])


def remove(conn: sqlite3.Connection, link_id: str) -> bool:
    """Remove a link you made. Wikilinks live in the note's text: edit the note instead."""
    row = conn.execute("SELECT kind FROM links WHERE id = ?", (link_id,)).fetchone()
    if row is None:
        return False
    if row["kind"] == "wikilink":
        raise ValueError("this link comes from the note's text; remove the [[link]] there")
    conn.execute("DELETE FROM links WHERE id = ?", (link_id,))
    return True


def all_links(conn: sqlite3.Connection) -> list[LinkRow]:
    """Every resolved link between two live items."""
    rows = conn.execute(
        "SELECT l.id, l.from_id, l.to_id, l.kind, l.state, l.strength FROM links l"
        " JOIN items a ON a.id = l.from_id AND a.trashed_at IS NULL"
        " JOIN items b ON b.id = l.to_id AND b.trashed_at IS NULL"
        " ORDER BY l.created_at"
    ).fetchall()
    return [LinkRow(r["id"], r["from_id"], r["to_id"], r["kind"], r["state"], float(r["strength"])) for r in rows]


def item_links(conn: sqlite3.Connection, item_id: str) -> tuple[list[LinkRow], list[LinkRow], list[str]]:
    """(outgoing, incoming, unresolved wikilink titles) for one item, live items only."""
    outgoing, incoming = [], []
    rows = conn.execute(
        "SELECT l.id, l.from_id, l.to_id, l.kind, l.state, l.strength FROM links l"
        " JOIN items o ON o.id = (CASE WHEN l.from_id = ? THEN l.to_id ELSE l.from_id END) AND o.trashed_at IS NULL"
        " WHERE l.from_id = ? OR l.to_id = ? ORDER BY l.created_at",
        (item_id, item_id, item_id),
    ).fetchall()
    for r in rows:
        link = LinkRow(r["id"], r["from_id"], r["to_id"], r["kind"], r["state"], float(r["strength"]))
        (outgoing if r["from_id"] == item_id else incoming).append(link)
    pending = [
        r["to_title"]
        for r in conn.execute(
            "SELECT to_title FROM links WHERE from_id = ? AND to_id IS NULL ORDER BY created_at", (item_id,)
        )
    ]
    return outgoing, incoming, pending
