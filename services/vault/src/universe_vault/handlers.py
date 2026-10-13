"""What a worker does with each job kind."""

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow
from universe_vault import jobs, sidecar, store
from universe_vault.ingest import add_version, import_file, walk_folder
from universe_vault.jobs import Job
from universe_vault.layout import Vault, sha256_file
from universe_vault.media import OcrEngine, make_thumbnail
from universe_vault.models import (
    ModelInfo,
    OllamaUnavailable,
    SyncOllama,
    assignment,
    doc_prefix,
    pick_embedder,
    pick_vision,
)
from universe_vault.pipeline import StageContext, run_content_stages, run_stage, uses_sidecar
from universe_vault.vectors import VectorRow, VectorStore, table_name

EMBED_BATCH = 16
EMBED_MAX_CHARS = 2000
NO_EMBEDDER = "No embedding model in Ollama (try: ollama pull nomic-embed-text). Keyword search still works."
NO_VISION = "No vision model assigned (System → Models). Captions are opt-in."


class Retry(Exception):
    """Give the job back without counting an attempt (the model server is down or busy)."""

    def __init__(self, reason: str, delay_s: float = 60.0) -> None:
        super().__init__(reason)
        self.delay_s = delay_s


EmitFn = Callable[..., None]


@dataclass
class WorkerContext:
    conn: sqlite3.Connection
    vault: Vault
    worker_id: str
    ollama: SyncOllama | None
    vectors: VectorStore
    emit: EmitFn
    report_error: Callable[[str, str, str], None] = lambda _kind, _message, _stack: None
    flush_events: Callable[[], None] = lambda: None
    ocr: OcrEngine = field(default_factory=OcrEngine)
    _models: tuple[float, list[ModelInfo]] | None = None

    def stage_context(self) -> StageContext:
        return StageContext(self.conn, self.vault, self.emit, ocr=self.ocr, thumbnail=make_thumbnail)

    def models(self) -> list[ModelInfo]:
        if self.ollama is None:
            raise OllamaUnavailable("no Ollama configured")
        if self._models is None or time.monotonic() - self._models[0] > 30:
            self._models = (time.monotonic(), self.ollama.models())
        return self._models[1]


# ---------- import ----------


def handle_import(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    p = job.payload
    path = Path(p["path"])
    project_ids = p.get("project_ids") or []
    interactive = bool(p.get("interactive", True))
    if path.is_dir():
        count = 0
        with transaction(ctx.conn):
            for file in walk_folder(path, recursive=p.get("recursive", True), skip=ctx.vault.root):
                jobs.enqueue(
                    ctx.conn,
                    "import",
                    payload={**p, "path": str(file), "origin": str(file)},
                    priority_class=job.priority_class,  # type: ignore[arg-type]
                    priority=job.priority,
                )
                count += 1
        return {"queued_files": count}
    if not path.is_file():
        return {"status": "skipped", "reason": "missing"}
    folder_id = p.get("folder_id")
    if folder_id:
        return _import_watched(ctx, path, folder_id, project_ids)
    result = import_file(
        ctx.conn,
        ctx.vault,
        path,
        source_kind=p.get("source_kind", "drop"),
        origin=p.get("origin") or str(path),
        name=p.get("name"),
        project_ids=project_ids,
        actor=p.get("actor", "user"),
        interactive=interactive,
        api_key_id=p.get("api_key_id"),
    )
    if p.get("delete_source_after") and ctx.vault.in_cache(path):
        path.unlink(missing_ok=True)  # an upload staged in .universe/cache, never a file of yours
    _announce_import(ctx, result.status, result.item_id, result.project_ids_added)
    return {"status": result.status, "item_id": result.item_id, "reason": result.reason}


def _announce_import(ctx: WorkerContext, status: str, item_id: str | None, added: list[str]) -> None:
    if item_id is None:
        return
    row = store.get_row(ctx.conn, item_id)
    if row is None:
        return
    if status == "created":
        payload = {"item_id": item_id, "type": row["type"], "title": row["title"], "path": row["path"]}
        ctx.emit("item.created", payload, subject_id=item_id)
    elif added or status == "updated":
        ctx.emit("item.updated", {"item_id": item_id, "projects_added": added}, subject_id=item_id)


def _import_watched(ctx: WorkerContext, path: Path, folder_id: str, project_ids: list[str]) -> dict[str, Any]:
    stat = path.stat()
    seen = ctx.conn.execute("SELECT * FROM source_files WHERE path = ?", (str(path),)).fetchone()
    if seen and seen["size_bytes"] == stat.st_size and seen["mtime_ns"] == stat.st_mtime_ns and seen["item_id"]:
        return {"status": "unchanged"}
    content_hash = sha256_file(path)
    status, item_id, added = "duplicate", None, []
    if seen and seen["item_id"] and seen["content_hash"] != content_hash and store.get_row(ctx.conn, seen["item_id"]):
        version = add_version(ctx.conn, ctx.vault, seen["item_id"], new_source=path, actor="system")
        status, item_id = ("updated" if version else "unchanged"), seen["item_id"]
    else:
        result = import_file(
            ctx.conn,
            ctx.vault,
            path,
            source_kind="watched_folder",
            origin=str(path),
            project_ids=project_ids,
            actor="system",
            interactive=False,
            content_hash=content_hash,
        )
        status, item_id, added = result.status, result.item_id, result.project_ids_added
    ctx.conn.execute(
        "INSERT INTO source_files (path, folder_id, item_id, size_bytes, mtime_ns, content_hash, seen_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT (path) DO UPDATE SET folder_id = excluded.folder_id,"
        " item_id = COALESCE(excluded.item_id, item_id), size_bytes = excluded.size_bytes,"
        " mtime_ns = excluded.mtime_ns, content_hash = excluded.content_hash, seen_at = excluded.seen_at",
        (str(path), folder_id, item_id, stat.st_size, stat.st_mtime_ns, content_hash, utcnow()),
    )
    _announce_import(ctx, status, item_id, added)
    return {"status": status, "item_id": item_id}


# ---------- pipeline, caption, embed, sidecar ----------


def handle_pipeline(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    if job.item_id is None:
        return {"status": "no item"}
    ok = run_content_stages(ctx.stage_context(), job.item_id)
    return {"status": "done" if ok else "item gone"}


def _caption_stage(ctx: WorkerContext, model: ModelInfo) -> Callable[[Any, sqlite3.Row], dict[str, Any]]:
    def run(_stage_ctx: Any, row: sqlite3.Row) -> dict[str, Any]:
        assert ctx.ollama is not None
        text = ctx.ollama.caption(model.name, ctx.vault.abs(row["path"]))
        meta = json.loads(row["metadata"] or "{}")
        meta["caption"] = text
        with transaction(ctx.conn):
            store.replace_chunks(
                ctx.conn,
                row["id"],
                row["current_version"],
                ["caption"],
                [store.ChunkIn(text, "caption")] if text else [],
            )
            ctx.conn.execute("UPDATE items SET metadata = ? WHERE id = ?", (json.dumps(meta, default=str), row["id"]))
            store.set_stage(ctx.conn, row["id"], "caption", "running", model=model.name, model_version=model.digest)
        return {"chars": len(text)}

    return run


def handle_caption(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    item_id = job.item_id
    if item_id is None or store.get_row(ctx.conn, item_id) is None:
        return {"status": "item gone"}
    try:
        vision = pick_vision(ctx.models(), assignment(ctx.conn, "vision"))
    except OllamaUnavailable:
        vision = None
    if vision is None:
        store.set_stage(ctx.conn, item_id, "caption", "skipped", detail=NO_VISION)
    else:
        try:
            run_stage(ctx.stage_context(), item_id, "caption", _caption_stage(ctx, vision))
        except OllamaUnavailable as exc:
            store.set_stage(ctx.conn, item_id, "caption", "pending", detail="waiting for Ollama")
            raise Retry(str(exc)) from exc
    with transaction(ctx.conn):
        store.refresh_pipeline_status(ctx.conn, item_id)
        jobs.enqueue(ctx.conn, "embed", item_id=item_id, priority=5, idempotency_key=f"embed:{item_id}")
    return {"status": "skipped" if vision is None else "done"}


def _embed_texts(row: sqlite3.Row, chunks: list[sqlite3.Row], prefix: str) -> list[str]:
    title = row["title"]
    return [f"{prefix}{title}\n{c['text']}"[:EMBED_MAX_CHARS] for c in chunks]


def handle_embed(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    item_id = job.item_id
    row = store.get_row(ctx.conn, item_id) if item_id else None
    if row is None or item_id is None or row["trashed_at"] is not None:
        return {"status": "item gone"}
    try:
        embedder = pick_embedder(ctx.models(), assignment(ctx.conn, "embed_text"))
    except OllamaUnavailable as exc:
        store.set_stage(ctx.conn, item_id, "embed", "pending", detail="waiting for Ollama")
        raise Retry(str(exc), delay_s=120) from exc
    result: dict[str, Any]
    if embedder is None:
        store.set_stage(ctx.conn, item_id, "embed", "skipped", detail=NO_EMBEDDER)
        result = {"status": "skipped"}
    else:
        store.set_stage(
            ctx.conn,
            item_id,
            "embed",
            "running",
            model=embedder.name,
            model_version=embedder.digest,
            count_attempt=True,
        )
        chunks = store.item_chunks(ctx.conn, item_id)
        texts = _embed_texts(row, chunks, doc_prefix(embedder.name))
        vectors: list[list[float]] = []
        try:
            assert ctx.ollama is not None
            for start in range(0, len(texts), EMBED_BATCH):
                vectors.extend(ctx.ollama.embed(embedder.name, texts[start : start + EMBED_BATCH]))
                jobs.progress(ctx.conn, job.id, len(vectors) / max(1, len(texts)))
            ctx.vectors.replace_item(
                table_name(embedder.name, embedder.digest),
                item_id,
                [
                    VectorRow(int(c["id"]), item_id, row["type"], row["captured_at"], [float(x) for x in v])
                    for c, v in zip(chunks, vectors, strict=True)
                ],
            )
        except OllamaUnavailable as exc:
            store.set_stage(ctx.conn, item_id, "embed", "pending", detail="waiting for Ollama")
            raise Retry(str(exc), delay_s=120) from exc
        except Exception as exc:
            # The job retries with backoff; meanwhile the item shows why instead of "running" forever.
            store.set_stage(ctx.conn, item_id, "embed", "failed", error=f"{type(exc).__name__}: {exc}"[:1000])
            store.refresh_pipeline_status(ctx.conn, item_id)
            raise
        store.set_stage(
            ctx.conn,
            item_id,
            "embed",
            "done",
            model=embedder.name,
            model_version=embedder.digest,
            detail=json.dumps({"chunks": len(chunks), "dim": len(vectors[0]) if vectors else 0}),
        )
        result = {"status": "done", "model": embedder.name, "chunks": len(chunks)}
    if uses_sidecar(row["type"], row["path"]):
        sidecar.write(ctx.conn, ctx.vault, item_id)
        store.set_stage(ctx.conn, item_id, "sidecar", "done")
    status = store.refresh_pipeline_status(ctx.conn, item_id)
    ctx.emit("item.processed", {"item_id": item_id, "pipeline_status": status, **result}, subject_id=item_id)
    return result


def handle_sidecar(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    if job.item_id is None:
        return {}
    row = store.get_row(ctx.conn, job.item_id)
    if row is None or not uses_sidecar(row["type"], row["path"]):
        return {"status": "not applicable"}
    return {"written": sidecar.write(ctx.conn, ctx.vault, job.item_id)}


def handle_reembed(ctx: WorkerContext, job: Job) -> dict[str, Any]:
    """After the embedding model changes (or appears): queue items whose vectors are missing or stale."""
    try:
        embedder = pick_embedder(ctx.models(), assignment(ctx.conn, "embed_text"))
    except OllamaUnavailable as exc:
        raise Retry(str(exc), delay_s=300) from exc
    if embedder is None:
        return {"queued": 0}
    rows = ctx.conn.execute(
        "SELECT i.id FROM items i LEFT JOIN item_stages s ON s.item_id = i.id AND s.stage = 'embed'"
        " WHERE i.trashed_at IS NULL AND i.pipeline_status != 'pending'"
        " AND (s.status IS NULL OR s.status IN ('skipped', 'failed') OR s.model_version IS NOT ?"
        " OR s.model IS NOT ?)",
        (embedder.digest, embedder.name),
    ).fetchall()
    with transaction(ctx.conn):
        for r in rows:
            store.set_stage(ctx.conn, r["id"], "embed", "pending", detail=f"queued for {embedder.name}")
            jobs.enqueue(ctx.conn, "embed", item_id=r["id"], priority=-5, idempotency_key=f"embed:{r['id']}")
    return {"queued": len(rows), "model": embedder.name}


HANDLERS: dict[str, Callable[[WorkerContext, Job], dict[str, Any]]] = {
    "import": handle_import,
    "pipeline": handle_pipeline,
    "caption": handle_caption,
    "embed": handle_embed,
    "sidecar": handle_sidecar,
    "reembed": handle_reembed,
}
