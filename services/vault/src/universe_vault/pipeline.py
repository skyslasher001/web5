"""The ingestion pipeline (SPEC §5): which stages an item gets, and the content stages themselves.

Job chain per item: `pipeline` (metadata → extract | ocr + thumbnail) → `caption` (images, when a vision
model is assigned) → `embed` (text embeddings, then the sidecar and `item.processed`). Stages that need
a later phase are recorded as skipped with the reason, so every item shows an honest pipeline status.
"""

import json
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow
from universe_vault import jobs, links, store
from universe_vault.extract import ExtractionError, chunk_sections, extract_text
from universe_vault.filetypes import IMAGE_TYPES, TEXT_TYPES, TIME_BASED_TYPES
from universe_vault.layout import Vault
from universe_vault.metadata import extract as extract_metadata

Emit = Callable[..., None]
TRANSCRIBE_LATER = "Transcription arrives with the voice service (Phase 7)"
MARKDOWN_TYPES = frozenset({"note", "idea", "link"})


def uses_sidecar(item_type: str, path: str) -> bool:
    return not (item_type in MARKDOWN_TYPES and path.lower().endswith((".md", ".markdown")))


def initial_stages(item_type: str) -> list[tuple[str, str, str | None]]:
    stages: list[tuple[str, str, str | None]] = [("metadata", "pending", None)]
    if item_type in TEXT_TYPES:
        stages.append(("extract", "pending", None))
    if item_type in IMAGE_TYPES:
        stages += [("thumbnail", "pending", None), ("ocr", "pending", None), ("caption", "pending", None)]
    if item_type in TIME_BASED_TYPES:
        stages.append(("transcribe", "skipped", TRANSCRIBE_LATER))
    stages.append(("embed", "pending", None))
    if item_type not in MARKDOWN_TYPES:
        stages.append(("sidecar", "pending", None))
    return stages


@dataclass
class StageContext:
    conn: sqlite3.Connection
    vault: Vault
    emit: Emit
    ocr: Callable[[Any], str] | None = None  # set by the worker (lazy RapidOCR)
    thumbnail: Callable[[Any, Any], bool] | None = None


class StageSkipped(Exception):
    """The stage doesn't apply to this item (e.g. a file with no text). Not an error."""


def _metadata_chunk_text(row: sqlite3.Row, meta: dict[str, Any]) -> str:
    """A small text unit for every item, so titles and tags are searchable even with no body text."""
    parts = [row["title"], row["type"].replace("_", " ")]
    for key in ("artist", "album", "genre", "composer", "year", "camera", "author", "subject", "url", "html_title"):
        if meta.get(key):
            parts.append(f"{key}: {meta[key]}")
    if meta.get("duration"):
        parts.append(f"duration: {int(float(meta['duration']) // 60)}m{int(float(meta['duration']) % 60):02d}s")
    return "\n".join(str(p) for p in parts)


def stage_metadata(ctx: StageContext, row: sqlite3.Row) -> dict[str, Any]:
    path = ctx.vault.abs(row["path"])
    meta = {**json.loads(row["metadata"] or "{}"), **extract_metadata(path, row["type"])}
    captured = meta.get("taken_at") or row["captured_at"]
    with transaction(ctx.conn):
        ctx.conn.execute(
            "UPDATE items SET metadata = ?, captured_at = ?, lat = ?, lon = ?, updated_at = ? WHERE id = ?",
            (json.dumps(meta, default=str), captured, meta.get("lat"), meta.get("lon"), utcnow(), row["id"]),
        )
        store.replace_chunks(
            ctx.conn,
            row["id"],
            row["current_version"],
            ["metadata"],
            [store.ChunkIn(_metadata_chunk_text(row, meta), kind="metadata")],
        )
        store.reindex_item(ctx.conn, row["id"])
    return {"keys": sorted(meta)}


def stage_extract(ctx: StageContext, row: sqlite3.Row) -> dict[str, Any]:
    path = ctx.vault.abs(row["path"])
    try:
        result = extract_text(path)
    except ExtractionError as exc:
        if row["type"] == "file":
            raise StageSkipped(str(exc)) from exc  # an unknown binary format: nothing to read, not a failure
        raise
    chunks = chunk_sections(result.sections)
    meta = json.loads(row["metadata"] or "{}")
    for key, value in (result.extra or {}).items():
        if value not in (None, "", [], {}):
            meta[key] = value
    meta["text_chars"] = result.chars
    if result.truncated:
        meta["text_truncated"] = True
    with transaction(ctx.conn):
        store.replace_chunks(
            ctx.conn,
            row["id"],
            row["current_version"],
            ["text"],
            [store.ChunkIn(c.text, "text", c.page, c.char_start, c.char_end) for c in chunks],
        )
        ctx.conn.execute(
            "UPDATE items SET metadata = ?, updated_at = ? WHERE id = ?",
            (json.dumps(meta, default=str), utcnow(), row["id"]),
        )
        store.reindex_item(ctx.conn, row["id"])
        if str(row["path"]).lower().endswith((".md", ".markdown")):
            links.sync_wikilinks(ctx.conn, row["id"], path.read_text(encoding="utf-8", errors="replace"))
    if not chunks:
        raise StageSkipped(
            "no text found" + (" (scanned PDF: page OCR comes later)" if meta.get("no_text_layer") else "")
        )
    return {"chunks": len(chunks), "chars": result.chars, "truncated": result.truncated}


def stage_thumbnail(ctx: StageContext, row: sqlite3.Row) -> dict[str, Any]:
    if ctx.thumbnail is None:
        raise StageSkipped("no thumbnailer")
    ok = ctx.thumbnail(ctx.vault.abs(row["path"]), ctx.vault.thumb_path(row["id"]))
    if not ok:
        raise StageSkipped("not a decodable image")
    return {}


def stage_ocr(ctx: StageContext, row: sqlite3.Row) -> dict[str, Any]:
    if ctx.ocr is None:
        raise StageSkipped("OCR engine unavailable")
    text = ctx.ocr(ctx.vault.abs(row["path"])).strip()
    with transaction(ctx.conn):
        store.replace_chunks(
            ctx.conn, row["id"], row["current_version"], ["ocr"], [store.ChunkIn(text, "ocr")] if text else []
        )
    if not text:
        raise StageSkipped("no text in the image")
    return {"chars": len(text)}


CONTENT_STAGES: dict[str, Callable[[StageContext, sqlite3.Row], dict[str, Any]]] = {
    "metadata": stage_metadata,
    "extract": stage_extract,
    "thumbnail": stage_thumbnail,
    "ocr": stage_ocr,
}


def run_stage(ctx: StageContext, item_id: str, stage: str, fn: Callable[[StageContext, sqlite3.Row], Any]) -> bool:
    """Run one stage and record its outcome. Content problems are recorded; unexpected errors propagate (retry)."""
    row = store.get_row(ctx.conn, item_id)
    if row is None or row["trashed_at"] is not None:
        return False
    store.set_stage(ctx.conn, item_id, stage, "running", count_attempt=True)
    ctx.emit("pipeline.stage.started", {"item_id": item_id, "stage": stage}, subject_id=item_id)
    try:
        info = fn(ctx, row)
    except StageSkipped as exc:
        store.set_stage(ctx.conn, item_id, stage, "skipped", detail=str(exc)[:500])
        ctx.emit("pipeline.stage.completed", {"item_id": item_id, "stage": stage, "skipped": True}, subject_id=item_id)
        return True
    except ExtractionError as exc:
        store.set_stage(ctx.conn, item_id, stage, "failed", error=str(exc)[:1000])
        ctx.emit(
            "pipeline.stage.failed", {"item_id": item_id, "stage": stage, "error": str(exc)[:300]}, subject_id=item_id
        )
        return True
    except Exception as exc:
        store.set_stage(ctx.conn, item_id, stage, "failed", error=f"{type(exc).__name__}: {exc}"[:1000])
        store.refresh_pipeline_status(ctx.conn, item_id)
        raise
    store.set_stage(ctx.conn, item_id, stage, "done", detail=json.dumps(info)[:500] if info else None)
    ctx.emit("pipeline.stage.completed", {"item_id": item_id, "stage": stage}, subject_id=item_id)
    return True


def run_content_stages(ctx: StageContext, item_id: str) -> bool:
    """The `pipeline` job: content stages that are still pending (resumable), then queue the next job."""
    todo = {
        row["stage"]
        for row in ctx.conn.execute(
            "SELECT stage FROM item_stages WHERE item_id = ? AND status IN ('pending', 'running', 'failed')", (item_id,)
        )
    }
    for stage, fn in CONTENT_STAGES.items():
        if stage in todo and not run_stage(ctx, item_id, stage, fn):
            return False  # the item was trashed or deleted meanwhile
    row = store.get_row(ctx.conn, item_id)
    if row is None:
        return False
    with transaction(ctx.conn):
        store.refresh_pipeline_status(ctx.conn, item_id)
        next_kind = "caption" if row["type"] in IMAGE_TYPES else "embed"
        jobs.enqueue(
            ctx.conn,
            next_kind,
            item_id=item_id,
            priority_class="background",
            priority=5,
            idempotency_key=f"{next_kind}:{item_id}",
        )
    return True
