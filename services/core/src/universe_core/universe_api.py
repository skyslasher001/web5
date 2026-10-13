"""REST for the universe view (ADR-0012): the scene data as columns, links, the cached Semantic layout,
note editing and similar items. Every handler is `async def`; vault work goes through `ctx.vdb.run`.
"""

import json
import sqlite3
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from universe_common.schema import ApiModel
from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow
from universe_core.context import CoreContext
from universe_vault import ingest, jobs, links, store
from universe_vault.schemas import ItemSummary
from universe_vault.vectors import table_name

router = APIRouter(prefix="/api/v1", tags=["universe"])
PAGE = 10_000


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]


class UniverseItems(ApiModel):
    """Items as parallel columns: the renderer keeps them in typed arrays, never one object per item."""

    ids: list[str]
    types: list[str]
    titles: list[str]
    galaxies: list[str | None]  # the galaxy (project) an item first joined
    created: list[int]  # epoch seconds
    captured: list[int]
    opened: list[int]  # epoch seconds, 0 = never opened
    opens: list[int]
    statuses: list[str]
    idea_stages: list[str | None]
    pinned: list[bool]
    removed: list[str]  # with `since`: items trashed since then
    next_cursor: str | None
    total: int  # live items in the vault
    server_time: str  # pass back as `since` to get only what changed


class UniverseLinks(ApiModel):
    ids: list[str]
    sources: list[str]
    targets: list[str]
    kinds: list[str]
    states: list[str]
    strengths: list[float]


class SemanticLayout(ApiModel):
    status: Literal["ready", "computing", "unavailable"]
    reason: str | None
    model: str | None
    stale: bool
    ids: list[str]
    positions: list[float]  # x, y, z per id


class LinkRequest(BaseModel):
    from_id: str
    to_id: str


class LinkInfo(ApiModel):
    id: str
    kind: str
    state: str
    item: ItemSummary


class ItemLinks(ApiModel):
    outgoing: list[LinkInfo]
    incoming: list[LinkInfo]  # backlinks
    unresolved: list[str]  # [[titles]] that don't match an item yet


class NoteContent(ApiModel):
    item_id: str
    body: str
    version: int


class NoteEdit(BaseModel):
    body: str = Field(max_length=2_000_000)
    base_version: int = Field(ge=1)  # the version you edited: a newer one on disk is a conflict, not overwritten


def _epoch(value: str | None) -> int:
    return int(datetime.fromisoformat(value).timestamp()) if value else 0


def _items_page(conn: sqlite3.Connection, cursor: str | None, limit: int, since: str | None) -> UniverseItems:
    server_time = utcnow()
    after = int(cursor) if cursor else 0
    where = "i.rowid > ?"
    params: list[object] = [after]
    if since:
        where += " AND (i.updated_at > ? OR i.last_opened_at > ? OR i.trashed_at > ?)"
        params += [since, since, since]
    else:
        where += " AND i.trashed_at IS NULL"
    rows = conn.execute(
        "SELECT i.rowid AS rid, i.id, i.type, i.title, i.created_at, i.captured_at, i.last_opened_at, i.open_count,"  # noqa: S608 (fixed clauses, values bound)
        " i.status, i.idea_stage, i.pinned, i.trashed_at,"
        " (SELECT ip.project_id FROM item_projects ip WHERE ip.item_id = i.id ORDER BY ip.added_at LIMIT 1) AS galaxy"
        f" FROM items i WHERE {where} ORDER BY i.rowid LIMIT ?",
        (*params, limit + 1),
    ).fetchall()
    more = len(rows) > limit
    rows = rows[:limit]
    page = UniverseItems(
        ids=[],
        types=[],
        titles=[],
        galaxies=[],
        created=[],
        captured=[],
        opened=[],
        opens=[],
        statuses=[],
        idea_stages=[],
        pinned=[],
        removed=[],
        next_cursor=str(rows[-1]["rid"]) if more and rows else None,
        total=conn.execute("SELECT COUNT(*) FROM items WHERE trashed_at IS NULL").fetchone()[0],
        server_time=server_time,
    )
    for r in rows:
        if r["trashed_at"] is not None:
            page.removed.append(r["id"])
            continue
        page.ids.append(r["id"])
        page.types.append(r["type"])
        page.titles.append(r["title"])
        page.galaxies.append(r["galaxy"])
        page.created.append(_epoch(r["created_at"]))
        page.captured.append(_epoch(r["captured_at"]))
        page.opened.append(_epoch(r["last_opened_at"]))
        page.opens.append(r["open_count"])
        page.statuses.append(r["status"])
        page.idea_stages.append(r["idea_stage"])
        page.pinned.append(bool(r["pinned"]))
    return page


@router.get("/universe/items", response_model=UniverseItems)
async def universe_items(
    ctx: Ctx,
    cursor: str | None = None,
    limit: Annotated[int, Query(ge=1, le=PAGE)] = PAGE,
    since: str | None = None,
) -> UniverseItems:
    if cursor is not None and not cursor.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Bad cursor")
    return await ctx.vdb.run(_items_page, cursor, limit, since)


def _links(conn: sqlite3.Connection) -> UniverseLinks:
    rows = links.all_links(conn)
    return UniverseLinks(
        ids=[r.id for r in rows],
        sources=[r.from_id for r in rows],
        targets=[r.to_id for r in rows],
        kinds=[r.kind for r in rows],
        states=[r.state for r in rows],
        strengths=[r.strength for r in rows],
    )


@router.get("/universe/links", response_model=UniverseLinks)
async def universe_links(ctx: Ctx) -> UniverseLinks:
    return await ctx.vdb.run(_links)


# ---------- the Semantic layout (computed by a worker, cached per embedding model) ----------


def _semantic(conn: sqlite3.Connection, name: str, model: str) -> SemanticLayout:
    row = conn.execute(
        "SELECT item_count, data FROM layout_cache WHERE kind = 'semantic' AND model = ?", (name,)
    ).fetchone()
    embedded = conn.execute(
        "SELECT COUNT(*) FROM item_stages s JOIN items i ON i.id = s.item_id"
        " WHERE s.stage = 'embed' AND s.status = 'done' AND s.model = ? AND i.trashed_at IS NULL",
        (model,),
    ).fetchone()[0]
    if row is None:
        if embedded == 0:
            return SemanticLayout(
                status="unavailable",
                reason="No item has been embedded yet: the Semantic layout appears once search by meaning works.",
                model=model,
                stale=False,
                ids=[],
                positions=[],
            )
        with transaction(conn):
            jobs.enqueue(conn, "layout", priority_class="interactive", idempotency_key="layout:semantic")
        return SemanticLayout(
            status="computing",
            reason=f"Arranging {embedded} items by meaning…",
            model=model,
            stale=False,
            ids=[],
            positions=[],
        )
    stale = abs(embedded - row["item_count"]) > max(20, row["item_count"] // 20)
    if stale:
        with transaction(conn):
            jobs.enqueue(conn, "layout", priority_class="background", idempotency_key="layout:semantic")
    data = json.loads(row["data"])
    return SemanticLayout(
        status="ready", reason=None, model=model, stale=stale, ids=data["ids"], positions=data["positions"]
    )


@router.get("/layout/semantic", response_model=SemanticLayout)
async def semantic_layout(ctx: Ctx) -> SemanticLayout:
    embedder = await ctx.current_embedder()
    if embedder is None:
        return SemanticLayout(
            status="unavailable",
            reason="Needs an embedding model (try: ollama pull nomic-embed-text).",
            model=None,
            stale=False,
            ids=[],
            positions=[],
        )
    return await ctx.vdb.run(_semantic, table_name(embedder.name, embedder.digest), embedder.name)


# ---------- links ----------


def _item_links(conn: sqlite3.Connection, ctx: CoreContext, item_id: str) -> ItemLinks:
    if store.get_row(conn, item_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item")
    outgoing, incoming, pending = links.item_links(conn, item_id)
    others = [r.to_id for r in outgoing] + [r.from_id for r in incoming]
    found = store.summaries_by_id(conn, ctx.vault, others)
    return ItemLinks(
        outgoing=[LinkInfo(id=r.id, kind=r.kind, state=r.state, item=found[r.to_id]) for r in outgoing],
        incoming=[LinkInfo(id=r.id, kind=r.kind, state=r.state, item=found[r.from_id]) for r in incoming],
        unresolved=pending,
    )


@router.get("/items/{item_id}/links", response_model=ItemLinks)
async def item_links(ctx: Ctx, item_id: str) -> ItemLinks:
    return await ctx.vdb.run(_item_links, ctx, item_id)


def _add_link(conn: sqlite3.Connection, body: LinkRequest) -> str:
    with transaction(conn):
        return links.add(conn, body.from_id, body.to_id, kind="manual", actor="user")


@router.post("/links", status_code=status.HTTP_201_CREATED)
async def add_link(ctx: Ctx, body: LinkRequest) -> dict[str, str]:
    try:
        link_id = await ctx.vdb.run(_add_link, body)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    ctx.bus.publish("link.created", {"link_id": link_id, "from_id": body.from_id, "to_id": body.to_id}, actor="user")
    return {"id": link_id}


def _remove_link(conn: sqlite3.Connection, link_id: str) -> bool:
    with transaction(conn):
        return links.remove(conn, link_id)


@router.delete("/links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_link(ctx: Ctx, link_id: str) -> None:
    try:
        removed = await ctx.vdb.run(_remove_link, link_id)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if not removed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such link")
    ctx.bus.publish("link.deleted", {"link_id": link_id}, actor="user")


# ---------- editing notes ----------


def _note(conn: sqlite3.Connection, ctx: CoreContext, item_id: str) -> NoteContent:
    row = store.get_row(conn, item_id)
    if row is None or row["trashed_at"] is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such item")
    if not ingest.is_markdown(row):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Only Markdown notes can be edited in UNIVERSE")
    path = ctx.vault.abs(row["path"])
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The file is missing from the vault")
    _front, body = ingest.split_frontmatter(path.read_text(encoding="utf-8", errors="replace"))
    return NoteContent(item_id=item_id, body=body, version=row["current_version"])


@router.get("/items/{item_id}/content", response_model=NoteContent)
async def note_content(ctx: Ctx, item_id: str) -> NoteContent:
    return await ctx.vdb.run(_note, ctx, item_id)


def _edit(conn: sqlite3.Connection, ctx: CoreContext, item_id: str, body: NoteEdit) -> tuple[NoteContent, bool]:
    current = _note(conn, ctx, item_id)
    if current.version != body.base_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The note changed since you opened it (version {current.version}); reload it before saving",
        )
    n = ingest.edit_note(conn, ctx.vault, item_id, body.body, actor="user")
    return _note(conn, ctx, item_id), n is not None


@router.put("/items/{item_id}/content", response_model=NoteContent)
async def edit_note(ctx: Ctx, item_id: str, body: NoteEdit) -> NoteContent:
    note, changed = await ctx.vdb.run(_edit, ctx, item_id, body)
    if changed:
        ctx.bus.publish(
            "item.updated",
            {"item_id": item_id, "version": note.version, "edited": True},
            actor="user",
            subject_type="item",
            subject_id=item_id,
        )
    return note


# ---------- similar items ----------


@router.get("/items/{item_id}/similar", response_model=list[ItemSummary])
async def similar_items(ctx: Ctx, item_id: str, limit: Annotated[int, Query(ge=1, le=50)] = 12) -> list[ItemSummary]:
    embedder = await ctx.current_embedder()
    if embedder is None:
        return []
    name = table_name(embedder.name, embedder.digest)
    vector = await ctx.vdb.run(lambda _conn: ctx.vectors.item_mean(name, item_id))
    if vector is None:
        return []
    hits = await ctx.vdb.run(lambda _conn: ctx.vectors.search(name, vector, limit=limit * 4))
    ordered = list(dict.fromkeys(h.item_id for h in hits if h.item_id != item_id))[:limit]
    found = await ctx.vdb.run(store.summaries_by_id, ctx.vault, ordered)
    return [found[i] for i in ordered if i in found and found[i].trashed_at is None]
