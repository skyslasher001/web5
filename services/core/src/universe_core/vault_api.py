"""REST API for the vault (ARCHITECTURE.md §5.1, Phase 2): items, ingest and capture, search and recall,
the job queue, local API keys, and the internal endpoints workers report to.

Every handler is `async def`; vault work that touches files or runs queries goes through `ctx.vdb.run`
(a thread with its own SQLite connection), and events are published back on the event loop.
"""

import hashlib
import json
import re
import secrets
import sqlite3
import time
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from universe_common.errors import fingerprint_from_text
from universe_common.ids import uuid7
from universe_common.schema import ApiModel
from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow
from universe_core.context import CoreContext
from universe_core.events import CATALOG
from universe_vault import governor, ingest, jobs, purge, search, store
from universe_vault.filetypes import ItemType
from universe_vault.layout import slugify
from universe_vault.pipeline import initial_stages
from universe_vault.query import Project as QueryProject
from universe_vault.query import parse
from universe_vault.schemas import (
    Item,
    ItemPage,
    ItemText,
    JobInfo,
    ParsedQuery,
    QueueStats,
    SearchHit,
    SearchResponse,
)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2 GB per file through the local API
URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]


# ---------- auth for the local API (your scripts) and for workers ----------


class Caller(BaseModel):
    actor: str
    api_key_id: str | None = None


def _hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


class LocalApiAuth:
    """The UI's session token, or a local API key with the right scope (ARCHITECTURE.md §1.3, boundary 3)."""

    def __init__(self, scope: Literal["capture", "search"]) -> None:
        self.scope = scope

    async def __call__(self, request: Request) -> Caller:
        ctx: CoreContext = request.app.state.ctx
        supplied = request.headers.get("authorization", "")
        if secrets.compare_digest(supplied.encode(), f"Bearer {ctx.settings.session_token}".encode()):
            return Caller(actor="user")
        if supplied.startswith("Bearer uk_"):
            row = ctx.dbs.universe.execute(
                "SELECT id, scopes FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL",
                (_hash_key(supplied.removeprefix("Bearer ")),),
            ).fetchone()
            if row is not None and self.scope in json.loads(row["scopes"]):
                ctx.dbs.universe.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (utcnow(), row["id"]))
                return Caller(actor=f"external:{row['id']}", api_key_id=row["id"])
            if row is not None:
                raise HTTPException(status.HTTP_403_FORBIDDEN, f"This API key lacks the '{self.scope}' scope")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid token")


async def internal_auth(request: Request) -> None:
    ctx: CoreContext = request.app.state.ctx
    supplied = request.headers.get("authorization", "")
    if not secrets.compare_digest(supplied.encode(), f"Bearer {ctx.internal_token}".encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Missing or invalid internal token")


router = APIRouter(prefix="/api/v1")  # session token (added by the app)
local_api = APIRouter(prefix="/api/v1")  # session token or a scoped API key
internal = APIRouter(prefix="/api/v1/internal", dependencies=[Depends(internal_auth)], include_in_schema=False)


# ---------- schemas ----------


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=300)
    status: Literal["inbox", "triaged", "active", "archived"] | None = None
    type: ItemType | None = None
    pinned: bool | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=60)]] | None = Field(default=None, max_length=50)
    add_projects: list[str] = Field(default_factory=list, max_length=20)
    remove_projects: list[str] = Field(default_factory=list, max_length=20)


class DeleteResult(ApiModel):
    item_id: str
    trashed: bool
    deleted: bool


class OpenResult(ApiModel):
    item_id: str
    path: str
    abs_path: str
    open_count: int


class IngestRequest(BaseModel):
    paths: list[Annotated[str, Field(min_length=1, max_length=4096)]] = Field(min_length=1, max_length=1000)
    project_id: str | None = None


class Rejected(ApiModel):
    path: str
    reason: str


class IngestResult(ApiModel):
    queued: int
    rejected: list[Rejected] = Field(default_factory=list)


class CaptureRequest(BaseModel):
    text: str = Field(default="", max_length=200_000)
    url: str | None = Field(default=None, max_length=4096)
    title: str | None = Field(default=None, max_length=300)
    kind: Literal["note", "idea", "link"] | None = None
    project_id: str | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=60)]] = Field(default_factory=list, max_length=50)
    source: Literal["quick_capture", "clipboard", "api"] = "quick_capture"


class CaptureResult(ApiModel):
    item_id: str | None = None
    queued_files: int = 0
    status: Literal["created", "queued"]


class RecallRequest(BaseModel):
    q: str = Field(min_length=1, max_length=500)


class RecallResult(ApiModel):
    intent: Literal["open", "go_to", "show", "search"]
    action: Literal["open_item", "show_project", "show_results"]
    confidence: float
    target_id: str | None = None
    parsed: ParsedQuery
    hits: list[SearchHit]
    semantic: bool
    took_ms: float


class VaultInfo(ApiModel):
    root: str
    index: str
    items: int
    trashed: int
    bytes: int
    by_type: dict[str, int]
    embedder: str | None = None
    workers: list[dict[str, Any]] = Field(default_factory=list)


class ApiKeyRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    scopes: list[Literal["capture", "search"]] = Field(min_length=1)


class ApiKeyInfo(ApiModel):
    id: str
    name: str
    scopes: list[str]
    prefix: str
    created_at: str
    last_used_at: str | None = None
    revoked_at: str | None = None


class ApiKeyCreated(ApiModel):
    key: str
    info: ApiKeyInfo


class InternalEvent(BaseModel):
    type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    subject_type: str | None = None
    subject_id: str | None = None


class InternalEvents(BaseModel):
    events: list[InternalEvent] = Field(max_length=1000)


class InternalError(BaseModel):
    service: Literal["worker"]
    kind: str = Field(min_length=1, max_length=200)
    message: str = Field(max_length=10_000)
    stack: str = Field(default="", max_length=100_000)


# ---------- helpers ----------


def _projects(conn: sqlite3.Connection) -> list[QueryProject]:
    return [QueryProject(r["id"], r["name"], r["slug"]) for r in conn.execute("SELECT id, name, slug FROM projects")]


def _require_item(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = store.get_row(conn, item_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item")
    return row


def _item_event(ctx: CoreContext, event_type: str, item_id: str, **payload: Any) -> None:
    ctx.bus.publish(event_type, {"item_id": item_id, **payload}, subject_type="item", subject_id=item_id)


# ---------- items ----------


@router.get("/items", response_model=ItemPage)
async def list_items(
    ctx: Ctx,
    type: Annotated[list[ItemType] | None, Query()] = None,
    project: str | None = None,
    tag: str | None = None,
    item_status: Annotated[str | None, Query(alias="status")] = None,
    pipeline: Literal["pending", "processing", "done", "failed"] | None = None,
    pinned: bool | None = None,
    trashed: bool = False,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    sort: Literal["added", "captured", "opened", "title"] = "added",
    cursor: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> ItemPage:
    filters = store.ItemFilters(
        types=type or [],
        project_id=project,
        tag=tag,
        status=item_status,
        pipeline_status=pipeline,
        pinned=pinned,
        trashed=trashed,
        date_from=date_from,
        date_to=date_to,
    )
    try:
        return await ctx.vdb.run(store.list_items, ctx.vault, filters, sort=sort, cursor=cursor, limit=limit)
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid cursor") from exc


@router.get("/items/{item_id}", response_model=Item)
async def get_item(ctx: Ctx, item_id: str) -> Item:
    item = await ctx.vdb.run(store.get_item, ctx.vault, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item")
    return item


def _patch(conn: sqlite3.Connection, ctx: CoreContext, item_id: str, body: ItemPatch) -> dict[str, Any]:
    row = _require_item(conn, item_id)
    changed: dict[str, Any] = {}
    with transaction(conn):
        updates: dict[str, Any] = {}
        if body.title is not None and body.title != row["title"]:
            updates["title"], updates["slug"] = body.title, slugify(body.title)
        if body.status is not None and body.status != row["status"]:
            updates["status"] = body.status
        if body.type is not None and body.type != row["type"]:
            updates["type"] = body.type
        if body.pinned is not None and int(body.pinned) != row["pinned"]:
            updates["pinned"] = int(body.pinned)
        if updates:
            assignments = ", ".join(f"{k} = ?" for k in updates)
            conn.execute(
                f"UPDATE items SET {assignments}, updated_at = ? WHERE id = ?",  # noqa: S608 - fixed column names
                (*updates.values(), utcnow(), item_id),
            )
            changed.update({k: v for k, v in updates.items() if k != "slug"})
        if body.tags is not None:
            changed["tags"] = store.set_tags(conn, item_id, body.tags, "user")
        if body.add_projects:
            changed["projects_added"] = store.add_to_projects(conn, item_id, body.add_projects, "user")
        removed = [p for p in body.remove_projects if store.remove_from_project(conn, item_id, p)]
        if removed:
            changed["projects_removed"] = removed
        if changed:
            store.reindex_item(conn, item_id)
            jobs.enqueue(conn, "sidecar", item_id=item_id, priority=5, idempotency_key=f"sidecar:{item_id}")
    return changed


@router.patch("/items/{item_id}", response_model=Item)
async def patch_item(ctx: Ctx, item_id: str, body: ItemPatch) -> Item:
    changed = await ctx.vdb.run(_patch, ctx, item_id, body)
    if changed:
        _item_event(ctx, "item.updated", item_id, changes=changed)
        if "tags" in changed:
            ctx.bus.publish("tag.confirmed", {"item_id": item_id, "tags": changed["tags"]}, actor="user")
    return await get_item(ctx, item_id)


@router.delete("/items/{item_id}", response_model=DeleteResult)
async def delete_item(ctx: Ctx, item_id: str, permanent: bool = False) -> DeleteResult:
    await ctx.vdb.run(_require_item, item_id)
    if permanent:
        deleted = await ctx.purge_item(item_id)
        return DeleteResult(item_id=item_id, trashed=False, deleted=deleted)
    trashed = await ctx.vdb.run(purge.trash, ctx.vault, item_id)
    if trashed:
        _item_event(ctx, "item.trashed", item_id)
    return DeleteResult(item_id=item_id, trashed=trashed, deleted=False)


@router.post("/items/{item_id}/restore", response_model=Item)
async def restore_item(ctx: Ctx, item_id: str) -> Item:
    await ctx.vdb.run(_require_item, item_id)
    try:
        restored = await ctx.vdb.run(purge.restore, ctx.vault, item_id)
    except purge.PurgeError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if restored:
        _item_event(ctx, "item.restored", item_id)
    return await get_item(ctx, item_id)


def _record_open(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    _require_item(conn, item_id)
    conn.execute("UPDATE items SET open_count = open_count + 1, last_opened_at = ? WHERE id = ?", (utcnow(), item_id))
    return _require_item(conn, item_id)


@router.post("/items/{item_id}/open", response_model=OpenResult)
async def open_item(ctx: Ctx, item_id: str) -> OpenResult:
    row = await ctx.vdb.run(_record_open, item_id)
    _item_event(ctx, "item.opened", item_id, type=row["type"])
    return OpenResult(
        item_id=item_id, path=row["path"], abs_path=str(ctx.vault.abs(row["path"])), open_count=row["open_count"]
    )


def _reprocess(conn: sqlite3.Connection, item_id: str) -> None:
    row = _require_item(conn, item_id)
    with transaction(conn):
        for stage, stage_status, detail in initial_stages(row["type"]):
            store.set_stage(conn, item_id, stage, stage_status, detail=detail)
        store.refresh_pipeline_status(conn, item_id)
        jobs.enqueue(
            conn,
            "pipeline",
            item_id=item_id,
            priority_class="interactive",
            priority=10,
            idempotency_key=f"pipeline:{item_id}",
        )


@router.post("/items/{item_id}/reprocess", response_model=Item)
async def reprocess_item(ctx: Ctx, item_id: str) -> Item:
    await ctx.vdb.run(_reprocess, item_id)
    return await get_item(ctx, item_id)


@router.get("/items/{item_id}/thumbnail", response_class=FileResponse)
async def item_thumbnail(ctx: Ctx, item_id: str) -> FileResponse:
    path = ctx.vault.thumb_path(item_id)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No thumbnail")
    return FileResponse(path, media_type="image/webp", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/items/{item_id}/file", response_class=FileResponse)
async def item_file(ctx: Ctx, item_id: str) -> FileResponse:
    row = await ctx.vdb.run(_require_item, item_id)
    path = ctx.vault.abs(row["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing from the vault")
    return FileResponse(path, media_type=row["mime"] or "application/octet-stream", filename=path.name)


def _text(conn: sqlite3.Connection, item_id: str, limit: int) -> ItemText:
    _require_item(conn, item_id)
    chunks = store.item_chunks(conn, item_id)
    body = "\n\n".join(c["text"] for c in chunks if c["kind"] != "metadata")
    return ItemText(item_id=item_id, text=body[:limit], truncated=len(body) > limit, chunks=len(chunks))


@router.get("/items/{item_id}/text", response_model=ItemText)
async def item_text(ctx: Ctx, item_id: str, limit: int = Query(20_000, ge=100, le=500_000)) -> ItemText:
    return await ctx.vdb.run(_text, item_id, limit)


# ---------- ingest and capture ----------


def _queue_paths(conn: sqlite3.Connection, ctx: CoreContext, body: IngestRequest, actor: str) -> IngestResult:
    rejected: list[Rejected] = []
    queued = 0
    with transaction(conn):
        for raw in body.paths:
            path = Path(raw)
            if not path.is_absolute():
                rejected.append(Rejected(path=raw, reason="not an absolute path"))
            elif not path.exists():
                rejected.append(Rejected(path=raw, reason="does not exist"))
            elif ctx.vault.in_index(path):
                rejected.append(Rejected(path=raw, reason="inside the vault's index folder"))
            else:
                jobs.enqueue(
                    conn,
                    "import",
                    payload={
                        "path": str(path),
                        "origin": str(path),
                        "source_kind": "drop",
                        "project_ids": [body.project_id] if body.project_id else [],
                        "actor": actor,
                        "interactive": True,
                    },
                    priority_class="interactive",
                    priority=20,
                )
                queued += 1
    return IngestResult(queued=queued, rejected=rejected)


@router.post("/ingest/paths", response_model=IngestResult, status_code=status.HTTP_202_ACCEPTED)
async def ingest_paths(ctx: Ctx, body: IngestRequest) -> IngestResult:
    return await ctx.vdb.run(_queue_paths, ctx, body, "user")


def _slug_for(conn: sqlite3.Connection, project_id: str | None) -> list[str]:
    if not project_id:
        return []
    row = conn.execute("SELECT slug FROM projects WHERE id = ?", (project_id,)).fetchone()
    return [row["slug"]] if row else []


def _capture_text(conn: sqlite3.Connection, ctx: CoreContext, body: CaptureRequest, caller: Caller) -> str:
    text = body.text.strip()
    url = body.url or (text if URL_RE.match(text) else None)
    kind = body.kind or ("link" if url else "note")
    if url and text == url:
        text = ""
    return ingest.create_note(
        conn,
        ctx.vault,
        text,
        title=body.title,
        item_type=kind,
        url=url,
        project_ids=[body.project_id] if body.project_id else [],
        project_slugs=_slug_for(conn, body.project_id),
        tags=body.tags,
        source_kind="api" if caller.api_key_id else body.source,
        actor=caller.actor,
        api_key_id=caller.api_key_id,
    )


@local_api.post("/capture", response_model=CaptureResult, status_code=status.HTTP_201_CREATED)
async def capture(
    ctx: Ctx, body: CaptureRequest, caller: Annotated[Caller, Depends(LocalApiAuth("capture"))]
) -> CaptureResult:
    if not body.text.strip() and not body.url:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nothing to capture: send text or a url")
    item_id = await ctx.vdb.run(_capture_text, ctx, body, caller)
    row = await ctx.vdb.run(_require_item, item_id)
    _item_event(
        ctx, "item.created", item_id, type=row["type"], title=row["title"], path=row["path"], actor=caller.actor
    )
    return CaptureResult(item_id=item_id, status="created")


@local_api.post("/capture/files", response_model=CaptureResult, status_code=status.HTTP_202_ACCEPTED)
async def capture_files(
    ctx: Ctx,
    caller: Annotated[Caller, Depends(LocalApiAuth("capture"))],
    files: Annotated[list[UploadFile], File(description="One or more files")],
    project_id: Annotated[str | None, Form()] = None,
    source: Annotated[Literal["clipboard", "api", "drop"], Form()] = "api",
) -> CaptureResult:
    staging = ctx.vault.cache / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    staged: list[tuple[Path, str]] = []
    try:
        for upload in files:
            name = Path(upload.filename or "upload").name or "upload"
            dest = staging / f"{uuid7()}{Path(name).suffix}"
            size = 0
            with dest.open("wb") as out:
                while chunk := await upload.read(1024 * 1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD_BYTES:
                        raise HTTPException(413, f"{name} is larger than 2 GB")
                    out.write(chunk)
            staged.append((dest, name))
    except BaseException:
        for path, _name in staged:
            path.unlink(missing_ok=True)
        raise

    def queue(conn: sqlite3.Connection) -> int:
        with transaction(conn):
            for path, name in staged:
                jobs.enqueue(
                    conn,
                    "import",
                    payload={
                        "path": str(path),
                        "name": name,
                        "origin": name,
                        "source_kind": "api" if caller.api_key_id else source,
                        "project_ids": [project_id] if project_id else [],
                        "actor": caller.actor,
                        "api_key_id": caller.api_key_id,
                        "delete_source_after": True,
                    },
                    priority_class="interactive",
                    priority=20,
                )
        return len(staged)

    return CaptureResult(queued_files=await ctx.vdb.run(queue), status="queued")


# ---------- search and recall ----------


async def run_search(
    ctx: CoreContext,
    q: str,
    *,
    mode: Literal["keyword", "hybrid"],
    filters: search.Filters,
    limit: int,
) -> SearchResponse:
    started = time.perf_counter()
    projects = await ctx.vdb.run(_projects)
    parsed = parse(q, projects)
    vector, table, note = None, None, None
    if mode == "hybrid" and parsed.text:
        result = await ctx.embed_query(parsed.text)
        if isinstance(result, str):
            note = result
        else:
            vector, table = result
    embed_ms = (time.perf_counter() - started) * 1000
    response = await ctx.vdb.run(
        search.search,
        ctx.vault,
        parsed,
        filters,
        vectors=ctx.vectors,
        vector=vector,
        vector_table=table,
        limit=limit,
        semantic_note=note,
        query=q,
    )
    response.timings_ms["parse_and_embed"] = round(embed_ms, 2)
    response.took_ms = round((time.perf_counter() - started) * 1000, 2)
    return response


@local_api.get("/search", response_model=SearchResponse)
async def search_items(
    ctx: Ctx,
    caller: Annotated[Caller, Depends(LocalApiAuth("search"))],
    q: str = Query("", max_length=500),
    mode: Literal["keyword", "hybrid"] = "hybrid",
    type: Annotated[list[ItemType] | None, Query()] = None,
    project: str | None = None,
    tag: str | None = None,
    date_from: Annotated[str | None, Query(alias="from")] = None,
    date_to: Annotated[str | None, Query(alias="to")] = None,
    limit: int = Query(30, ge=1, le=200),
) -> SearchResponse:
    filters = search.Filters(types=type or [], project_id=project, tag=tag, date_from=date_from, date_to=date_to)
    return await run_search(ctx, q, mode=mode, filters=filters, limit=limit)


_OPEN = re.compile(r"^\s*(?:open|play|pull up|bring up|launch)\s+(?:the\s+|my\s+)?(.+)$", re.IGNORECASE)
_GO = re.compile(
    r"^\s*(?:go to|goto|take me to|jump to|switch to)\s+(?:the\s+)?(?:project\s+)?(.+?)(?:\s+project)?\s*$",
    re.IGNORECASE,
)
_SHOW = re.compile(r"^\s*(?:show|list|find|search for|search|look for)\s+(?:me\s+)?(.+)$", re.IGNORECASE)


@router.post("/recall", response_model=RecallResult)
async def recall(ctx: Ctx, body: RecallRequest) -> RecallResult:
    """The fast path (SPEC §6): a small intent grammar plus search. No LLM call."""
    started = time.perf_counter()
    q = body.q.strip()
    projects = await ctx.vdb.run(_projects)
    if (go := _GO.match(q)) is not None:
        wanted = go.group(1).strip().lower()
        for project in projects:
            names = {project.name.lower(), project.slug.replace("-", " "), project.slug}
            if wanted in names or any(n.startswith(wanted) for n in names if len(wanted) >= 3):
                parsed = ParsedQuery(text="", project_ids=[project.id])
                result = RecallResult(
                    intent="go_to",
                    action="show_project",
                    confidence=0.95,
                    target_id=project.id,
                    parsed=parsed,
                    hits=[],
                    semantic=False,
                    took_ms=round((time.perf_counter() - started) * 1000, 2),
                )
                ctx.bus.publish("recall.performed", {"q": q, "intent": "go_to", "target": project.id}, actor="user")
                return result
    intent: Literal["open", "show", "search"] = "search"
    text = q
    if (m := _OPEN.match(q)) is not None:
        intent, text = "open", m.group(1)
    elif (m := _SHOW.match(q)) is not None:
        intent, text = "show", m.group(1)
    response = await run_search(ctx, text, mode="hybrid", filters=search.Filters(), limit=12)
    hits = response.hits
    confidence = 0.0
    if hits:
        top = hits[0].score
        second = hits[1].score if len(hits) > 1 else 0.0
        title_hit = "title" in hits[0].matched or "trigram" in hits[0].matched
        confidence = 0.9 if len(hits) == 1 else min(0.95, 0.5 + 0.25 * (top / max(second, 1e-9) - 1))
        if title_hit:
            confidence = min(0.97, confidence + 0.1)
    action: Literal["open_item", "show_project", "show_results"] = (
        "open_item" if intent == "open" and hits and confidence >= 0.85 else "show_results"
    )
    ctx.bus.publish(
        "recall.performed",
        {"q": q, "intent": intent, "results": [h.item.id for h in hits[:5]], "action": action},
        actor="user",
    )
    return RecallResult(
        intent=intent,
        action=action,
        confidence=round(confidence, 3),
        target_id=hits[0].item.id if action == "open_item" else None,
        parsed=response.parsed,
        hits=hits,
        semantic=response.semantic,
        took_ms=round((time.perf_counter() - started) * 1000, 2),
    )


# ---------- jobs and the queue ----------


def _stats(conn: sqlite3.Connection, workers: int) -> QueueStats:
    state = governor.state(conn)
    return jobs.stats(
        conn, paused=state.paused, pause_reason=state.reason, model_hold=state.model_hold, workers=workers
    )


@router.get("/jobs", response_model=list[JobInfo])
async def list_jobs(
    ctx: Ctx,
    job_status: Annotated[
        Literal["queued", "leased", "succeeded", "dead", "cancelled"] | None, Query(alias="status")
    ] = None,
    kind: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[JobInfo]:
    return await ctx.vdb.run(jobs.list_jobs, status=job_status, kind=kind, limit=limit)


@router.get("/jobs/stats", response_model=QueueStats)
async def job_stats(ctx: Ctx) -> QueueStats:
    return await ctx.vdb.run(_stats, ctx.workers.count)


@router.post("/jobs/{job_id}/retry", response_model=JobInfo)
async def retry_job(ctx: Ctx, job_id: str) -> JobInfo:
    if not await ctx.vdb.run(jobs.retry, job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only dead or cancelled jobs can be retried")
    info = await ctx.vdb.run(jobs.get, job_id)
    assert info is not None
    return info


@router.post("/jobs/{job_id}/cancel", response_model=JobInfo)
async def cancel_job(ctx: Ctx, job_id: str) -> JobInfo:
    if not await ctx.vdb.run(jobs.cancel, job_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Only queued jobs can be cancelled")
    info = await ctx.vdb.run(jobs.get, job_id)
    assert info is not None
    return info


@router.post("/queue/pause", response_model=QueueStats)
async def pause_queue(ctx: Ctx) -> QueueStats:
    await ctx.vdb.run(governor.set_paused, True, "paused by you")
    ctx.bus.publish("governor.paused", {"reason": "paused by you"}, actor="user")
    return await job_stats(ctx)


@router.post("/queue/resume", response_model=QueueStats)
async def resume_queue(ctx: Ctx) -> QueueStats:
    await ctx.vdb.run(governor.set_paused, False)
    ctx.bus.publish("governor.resumed", {"reason": None}, actor="user")
    return await job_stats(ctx)


# ---------- vault info ----------


def _vault_info(conn: sqlite3.Connection, ctx: CoreContext) -> VaultInfo:
    by_type = {
        r["type"]: r["n"]
        for r in conn.execute("SELECT type, COUNT(*) AS n FROM items WHERE trashed_at IS NULL GROUP BY type")
    }
    totals = conn.execute(
        "SELECT COUNT(*) FILTER (WHERE trashed_at IS NULL) AS items, COUNT(*) FILTER (WHERE trashed_at IS NOT NULL)"
        " AS trashed, COALESCE(SUM(size_bytes), 0) AS bytes FROM items"
    ).fetchone()
    embedder = conn.execute("SELECT value FROM settings WHERE key = 'pipeline.embedder'").fetchone()
    return VaultInfo(
        root=str(ctx.vault.root),
        index=str(ctx.vault.index),
        items=totals["items"],
        trashed=totals["trashed"],
        bytes=totals["bytes"],
        by_type=by_type,
        embedder=(embedder["value"].split("@")[0] or None) if embedder else None,
        workers=ctx.workers.status(),
    )


@router.get("/system/vault", response_model=VaultInfo)
async def vault_info(ctx: Ctx) -> VaultInfo:
    return await ctx.vdb.run(_vault_info, ctx)


# ---------- local API keys ----------


def _key_info(row: sqlite3.Row) -> ApiKeyInfo:
    return ApiKeyInfo(
        id=row["id"],
        name=row["name"],
        scopes=json.loads(row["scopes"]),
        prefix=row["prefix"],
        created_at=row["created_at"],
        last_used_at=row["last_used_at"],
        revoked_at=row["revoked_at"],
    )


@router.get("/api-keys", response_model=list[ApiKeyInfo])
async def list_api_keys(ctx: Ctx) -> list[ApiKeyInfo]:
    rows = ctx.dbs.universe.execute("SELECT * FROM api_keys ORDER BY created_at DESC").fetchall()
    return [_key_info(r) for r in rows]


@router.post("/api-keys", response_model=ApiKeyCreated, status_code=status.HTTP_201_CREATED)
async def create_api_key(ctx: Ctx, body: ApiKeyRequest) -> ApiKeyCreated:
    key = f"uk_{secrets.token_urlsafe(32)}"
    key_id = uuid7()
    ctx.dbs.universe.execute(
        "INSERT INTO api_keys (id, name, scopes, key_hash, prefix, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (key_id, body.name, json.dumps(sorted(set(body.scopes))), _hash_key(key), key[:7], utcnow()),
    )
    ctx.audit.append(
        actor="user", action="api_key.created", target_type="api_key", target_id=key_id, details={"scopes": body.scopes}
    )
    row = ctx.dbs.universe.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    return ApiKeyCreated(key=key, info=_key_info(row))


@router.delete("/api-keys/{key_id}", response_model=ApiKeyInfo)
async def revoke_api_key(ctx: Ctx, key_id: str) -> ApiKeyInfo:
    cursor = ctx.dbs.universe.execute(
        "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", (utcnow(), key_id)
    )
    row = ctx.dbs.universe.execute("SELECT * FROM api_keys WHERE id = ?", (key_id,)).fetchone()
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such key")
    if cursor.rowcount:
        ctx.audit.append(actor="user", action="api_key.revoked", target_type="api_key", target_id=key_id, details={})
    return _key_info(row)


# ---------- internal: workers report here ----------

WORKER_EVENTS = {t for t in CATALOG if t.startswith(("item.", "pipeline.", "job."))} | {"layout.updated"}


@internal.post("/events")
async def internal_events(ctx: Ctx, body: InternalEvents) -> dict[str, int]:
    published = 0
    for event in body.events:
        if event.type not in WORKER_EVENTS:
            continue
        ctx.bus.publish(
            event.type,
            event.payload,
            subject_type=event.subject_type,
            subject_id=event.subject_id,
            source="worker",
        )
        published += 1
    return {"published": published}


@internal.post("/errors")
async def internal_errors(ctx: Ctx, body: InternalError) -> dict[str, bool]:
    ctx.errors.record(
        service=body.service,
        kind=body.kind,
        message=body.message,
        stack=body.stack,
        fingerprint=fingerprint_from_text(body.kind, body.message, body.stack),
    )
    return {"recorded": True}
