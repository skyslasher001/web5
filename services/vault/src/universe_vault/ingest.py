"""Getting things into the vault: copy (never move or modify the source), hash, dedupe, record, queue.

Every way in (drag-drop, watched folders, quick capture, clipboard, the local API) ends here.
"""

import contextlib
import json
import os
import re
import shutil
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal

from universe_common.ids import uuid7
from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow
from universe_vault import jobs, store
from universe_vault.filetypes import ItemType, detect_type, guess_mime
from universe_vault.layout import SIDECAR_SUFFIX, Vault, sha256_file, slugify
from universe_vault.metadata import captured_at, note_title
from universe_vault.pipeline import initial_stages

DEFAULT_EXCLUDES = (
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", ".tox", ".mypy_cache",
    ".pytest_cache", ".ruff_cache", ".next", "dist", "build", ".idea", ".vs", ".DS_Store", "Thumbs.db",
    "desktop.ini", "*.tmp", "*.part", "*.crdownload", "~$*", ".~lock.*", "*.universe.json",
)  # fmt: skip
MAX_FOLDER_FILES = 100_000

ImportStatus = Literal["created", "duplicate", "updated", "skipped"]


@dataclass
class ImportResult:
    status: ImportStatus
    item_id: str | None = None
    path: str | None = None
    reason: str | None = None
    created: bool = False
    project_ids_added: list[str] = field(default_factory=list)


def excluded(path: Path, patterns: Iterable[str]) -> bool:
    return any(fnmatch(part, pattern) for part in path.parts for pattern in patterns)


def walk_folder(
    folder: Path,
    *,
    recursive: bool = True,
    include: Iterable[str] = (),
    exclude: Iterable[str] = (),
    skip: Path | None = None,
) -> Iterator[Path]:
    """Files under `folder`, minus default and custom excludes (and `skip`, e.g. the vault itself)."""
    patterns = (*DEFAULT_EXCLUDES, *exclude)
    include = tuple(include)
    count = 0
    for root, dirs, files in os.walk(folder):
        root_path = Path(root)
        if skip is not None and (root_path == skip or skip in root_path.parents):
            dirs[:] = []
            continue
        dirs[:] = sorted(d for d in dirs if not excluded(Path(d), patterns))
        if not recursive:
            dirs[:] = []
        for name in sorted(files):
            if excluded(Path(name), patterns):
                continue
            if include and not any(fnmatch(name, p) for p in include):
                continue
            yield root_path / name
            count += 1
            if count >= MAX_FOLDER_FILES:
                return


def _queue_pipeline(conn: sqlite3.Connection, item_id: str, *, interactive: bool) -> None:
    jobs.enqueue(
        conn,
        "pipeline",
        item_id=item_id,
        priority_class="interactive" if interactive else "background",
        priority=10 if interactive else 0,
        idempotency_key=f"pipeline:{item_id}",
    )


def _insert_item(
    conn: sqlite3.Connection,
    *,
    item_id: str,
    item_type: ItemType,
    title: str,
    rel_path: str,
    size: int,
    content_hash: str,
    when: str,
    source_id: str,
    actor: str,
    version_path: str,
    metadata: dict[str, object] | None = None,
) -> None:
    now = utcnow()
    conn.execute(
        "INSERT INTO items (id, type, title, slug, path, mime, size_bytes, content_hash, captured_at, metadata,"
        " source_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            item_id,
            item_type,
            title,
            slugify(title),
            rel_path,
            guess_mime(rel_path),
            size,
            content_hash,
            when,
            json.dumps(metadata or {}),
            source_id,
            now,
            now,
        ),
    )
    conn.execute(
        "INSERT INTO versions (id, item_id, n, path, content_hash, size_bytes, created_by, note, created_at)"
        " VALUES (?, ?, 1, ?, ?, ?, ?, 'original', ?)",
        (uuid7(), item_id, version_path, content_hash, size, actor, now),
    )
    for stage, status, detail in initial_stages(item_type):
        store.set_stage(conn, item_id, stage, status, detail=detail)
    store.reindex_item(conn, item_id)


def _keep_note_version(vault: Vault, item_id: str, n: int, src: Path) -> str:
    """Notes can be edited outside the app, so each version's bytes are kept under .universe/versions/."""
    dest = vault.version_dir(item_id) / f"{n}{src.suffix}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return vault.rel(dest)


def import_file(
    conn: sqlite3.Connection,
    vault: Vault,
    src: Path,
    *,
    source_kind: str,
    origin: str | None = None,
    name: str | None = None,
    project_ids: Iterable[str] = (),
    actor: str = "user",
    interactive: bool = True,
    api_key_id: str | None = None,
    content_hash: str | None = None,
) -> ImportResult:
    """Copy `src` into the vault as a new item (or recognise it as a duplicate). The source is untouched."""
    src = src.resolve()
    if not src.is_file():
        return ImportResult("skipped", reason="not a file")
    staged = vault.in_cache(src)  # an upload waiting in .universe/cache: copied in like any outside file
    if vault.in_index(src) and not staged:
        return ImportResult("skipped", reason="inside the vault index")
    if src.name.endswith(SIDECAR_SUFFIX):
        return ImportResult("skipped", reason="a vault sidecar")
    content_hash = content_hash or sha256_file(src)
    project_ids = list(project_ids)

    existing = store.find_by_hash(conn, content_hash)
    if existing is not None:
        with transaction(conn):
            added = store.add_to_projects(conn, existing["id"], project_ids, actor)
        return ImportResult("duplicate", existing["id"], existing["path"], project_ids_added=added)

    display_name = name or src.name
    item_type = detect_type(display_name)
    when = captured_at(src, item_type)
    if vault.contains(src) and not staged:
        dest = src  # already in the vault (you put it there): adopt it in place
    else:
        folder = vault.folder_for(item_type, when)
        folder.mkdir(parents=True, exist_ok=True)
        dest = vault.free_path(folder, display_name)
        tmp = dest.with_name(f".{dest.name}.{uuid7()}.part")
        shutil.copy2(src, tmp)
        os.replace(tmp, dest)
    rel_path = vault.rel(dest)
    title = Path(display_name).stem or display_name
    if item_type == "note":
        with contextlib.suppress(OSError):
            title = note_title(dest.read_text(encoding="utf-8", errors="replace")[:65536], title)
    item_id = uuid7()
    try:
        with transaction(conn):
            again = store.find_by_hash(conn, content_hash)  # another import may have won the race
            if again is not None:
                raise _Duplicate(again)
            source_id = store.create_source(conn, source_kind, origin, api_key_id=api_key_id)
            version_path = _keep_note_version(vault, item_id, 1, dest) if item_type == "note" else rel_path
            _insert_item(
                conn,
                item_id=item_id,
                item_type=item_type,
                title=title,
                rel_path=rel_path,
                size=dest.stat().st_size,
                content_hash=content_hash,
                when=when,
                source_id=source_id,
                actor=actor,
                version_path=version_path,
            )
            added = store.add_to_projects(conn, item_id, project_ids, actor)
            _queue_pipeline(conn, item_id, interactive=interactive)
    except _Duplicate as dup:
        if dest != src:
            dest.unlink(missing_ok=True)
        with transaction(conn):
            added = store.add_to_projects(conn, dup.row["id"], project_ids, actor)
        return ImportResult("duplicate", dup.row["id"], dup.row["path"], project_ids_added=added)
    except BaseException:
        if dest != src:
            dest.unlink(missing_ok=True)
        raise
    return ImportResult("created", item_id, rel_path, created=True, project_ids_added=added)


class _Duplicate(Exception):
    def __init__(self, row: sqlite3.Row) -> None:
        self.row = row


def is_markdown(row: sqlite3.Row) -> bool:
    return str(row["path"]).lower().endswith((".md", ".markdown"))


def add_version(
    conn: sqlite3.Connection,
    vault: Vault,
    item_id: str,
    *,
    new_source: Path | None,
    actor: str,
    note: str | None = None,
) -> int | None:
    """Record a new version of an item whose bytes changed. Returns the version number, or None if unchanged.

    - `new_source` given (a changed file in a watched folder): its bytes are copied into a fresh vault
      file; the old vault file stays as the previous version.
    - `new_source` None (the vault file itself was edited, e.g. in Obsidian): Markdown keeps every
      version under `.universe/versions/`; other files record the edit, but the editor already replaced
      the old bytes in place, so only the history entry remains.
    """
    row = store.get_row(conn, item_id)
    if row is None or row["trashed_at"] is not None:
        return None
    current = vault.abs(row["path"])
    source = new_source or current
    content_hash = sha256_file(source)
    if content_hash == row["content_hash"]:
        return None
    n = int(row["current_version"]) + 1
    note = note or "changed on disk"
    if new_source is not None:
        dest = vault.free_path(current.parent, current.name)
        tmp = dest.with_name(f".{dest.name}.{uuid7()}.part")
        shutil.copy2(source, tmp)
        os.replace(tmp, dest)
        rel_path = version_path = vault.rel(dest)
        note = "source changed"
    elif is_markdown(row):
        version_path = _keep_note_version(vault, item_id, n, current)
        rel_path = row["path"]
    else:
        rel_path = version_path = row["path"]
        note = "edited in place outside the app (previous bytes not kept)"
    size = vault.abs(rel_path).stat().st_size
    with transaction(conn):
        conn.execute(
            "INSERT INTO versions (id, item_id, n, path, content_hash, size_bytes, created_by, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (uuid7(), item_id, n, version_path, content_hash, size, actor, note, utcnow()),
        )
        conn.execute(
            "UPDATE items SET path = ?, content_hash = ?, size_bytes = ?, current_version = ?, updated_at = ?"
            " WHERE id = ?",
            (rel_path, content_hash, size, n, utcnow(), item_id),
        )
        if is_markdown(row):
            title = note_title(vault.abs(rel_path).read_text(encoding="utf-8", errors="replace")[:65536], row["title"])
            conn.execute("UPDATE items SET title = ?, slug = ? WHERE id = ?", (title, slugify(title), item_id))
        for stage, status, detail in initial_stages(row["type"]):
            store.set_stage(conn, item_id, stage, status, detail=detail)
        store.refresh_pipeline_status(conn, item_id)
        store.reindex_item(conn, item_id)
        _queue_pipeline(conn, item_id, interactive=False)
    return n


FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n(?:\r?\n)?", re.DOTALL)


def split_frontmatter(text: str) -> tuple[str, str]:
    """(frontmatter block including its fences, body) of a Markdown note."""
    match = FRONTMATTER.match(text)
    return (match.group(0), text[match.end() :]) if match else ("", text)


def edit_note(conn: sqlite3.Connection, vault: Vault, item_id: str, body: str, *, actor: str = "user") -> int | None:
    """Replace a Markdown note's body (its frontmatter stays) and record a new version. None if unchanged."""
    row = store.get_row(conn, item_id)
    if row is None or row["trashed_at"] is not None:
        raise LookupError(f"no item with id {item_id}")
    if not is_markdown(row):
        raise ValueError("only Markdown notes can be edited in UNIVERSE")
    path = vault.abs(row["path"])
    front, _old = split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    content = front + body.rstrip() + "\n"
    tmp = path.with_name(f".{path.name}.{uuid7()}.part")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, path)
    return add_version(conn, vault, item_id, new_source=None, actor=actor, note="edited in UNIVERSE")


def deleted_outside(conn: sqlite3.Connection, vault: Vault, rel_path: str) -> str | None:
    """The file of an item was deleted outside the app: move the item to the trash (purged after 30 days)."""
    row = store.find_by_path(conn, rel_path)
    if row is None or row["trashed_at"] is not None or vault.abs(rel_path).exists():
        return None
    with transaction(conn):
        conn.execute(
            "UPDATE items SET trashed_at = ?, metadata = json_set(metadata, '$.deleted_outside_app', json('true')),"
            " updated_at = ? WHERE id = ?",
            (utcnow(), utcnow(), row["id"]),
        )
        store.reindex_item(conn, row["id"])
    return row["id"]


def _frontmatter(fields: dict[str, object]) -> str:
    import yaml

    return "---\n" + yaml.safe_dump(fields, sort_keys=False, allow_unicode=True).strip() + "\n---\n\n"


def create_note(
    conn: sqlite3.Connection,
    vault: Vault,
    text: str,
    *,
    title: str | None = None,
    item_type: Literal["note", "idea", "link"] = "note",
    url: str | None = None,
    project_ids: Iterable[str] = (),
    project_slugs: Iterable[str] = (),
    tags: Iterable[str] = (),
    source_kind: str = "quick_capture",
    actor: str = "user",
    api_key_id: str | None = None,
) -> str:
    """Write a new Markdown note (Obsidian-compatible frontmatter) into the vault and index it."""
    text = text.strip()
    if not title:
        first = next((line.strip("# ").strip() for line in text.splitlines() if line.strip()), "")
        title = (first or url or "Quick note")[:80]
    item_id = uuid7()
    now = utcnow()
    tags = [t for t in dict.fromkeys(t.strip() for t in tags) if t]
    fields: dict[str, object] = {"id": item_id, "type": item_type, "title": title, "created": now, "status": "inbox"}
    if url:
        fields["url"] = url
    slugs = list(project_slugs)
    if slugs:
        fields["projects"] = slugs
    if tags:
        fields["tags"] = tags
    body = text if text else (f"<{url}>" if url else "")
    content = _frontmatter(fields) + body + "\n"
    folder = vault.folder_for(item_type, now)
    folder.mkdir(parents=True, exist_ok=True)
    dest = vault.free_path(folder, f"{slugify(title, max_len=60)}.md")
    tmp = dest.with_name(f".{dest.name}.{uuid7()}.part")
    tmp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(tmp, dest)
    rel_path = vault.rel(dest)
    content_hash = sha256_file(dest)
    try:
        with transaction(conn):
            source_id = store.create_source(conn, source_kind, url, api_key_id=api_key_id)
            _insert_item(
                conn,
                item_id=item_id,
                item_type=item_type,
                title=title,
                rel_path=rel_path,
                size=dest.stat().st_size,
                content_hash=content_hash,
                when=now,
                source_id=source_id,
                actor=actor,
                version_path=_keep_note_version(vault, item_id, 1, dest),
                metadata={"url": url} if url else None,
            )
            store.add_to_projects(conn, item_id, project_ids, actor)
            if tags:
                store.set_tags(conn, item_id, tags, actor)
                store.reindex_item(conn, item_id)
            _queue_pipeline(conn, item_id, interactive=True)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise
    return item_id
