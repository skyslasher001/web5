"""REST for Research (Phase 6, ADR-0015): start a research task, watchlists, and the "sent where" log.

A research task is an ordinary agent task run by the `researcher` agent — it streams steps, traces and
approvals through the existing agent-engine machinery and events. The only new surface is the mode-framed
instruction, the watchlist CRUD, and a read-only view of the egress audit for the privacy dashboard.
"""

import sqlite3
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from universe_common.egress import EgressDenied
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_core.agent_engine import EngineUnavailable
from universe_core.context import CoreContext
from universe_core.watchlists import WatchlistStore, check_one
from universe_research.fetch import FetchRefused

router = APIRouter(prefix="/api/v1")


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]

QUICK = (
    "Quick web research. Question:\n\n{q}\n\n"
    "Search the web, read one or two of the best sources, and give a concise answer with citations [n] and a "
    "Sources list. Do not save anything."
)
DEEP = (
    "Deep web research. Question:\n\n{q}\n\n"
    "Search broadly, cross-check several sources, then write a structured report (a short summary, the key "
    "findings with citations, any conflicts, and a Sources list) and save it to the vault with vault.save, "
    "passing the report text and the source URLs. Saving will ask the owner to approve."
)


class ResearchRequest(BaseModel):
    q: str = Field(min_length=2, max_length=2000, description="The research question")
    mode: Literal["quick", "deep"] = "quick"


class ResearchResponse(ApiModel):
    task_id: str
    agent_id: str = "researcher"


@router.post("/research", response_model=ResearchResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_research(ctx: Ctx, body: ResearchRequest) -> ResearchResponse:
    if ctx.engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agent engine is not running")
    template = DEEP if body.mode == "deep" else QUICK
    instruction = template.replace("{q}", body.q)
    try:
        task_id = ctx.engine.start("researcher", instruction)
    except EngineUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:  # the researcher agent is missing or turned off
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return ResearchResponse(task_id=task_id)


# ---------- the privacy dashboard: what was sent where (SPEC §17) ----------


class SentRequest(ApiModel):
    ts: str
    host: str
    purpose: str
    scheme: str
    path: str
    actor: str


@router.get("/research/requests", response_model=list[SentRequest])
async def research_requests(ctx: Ctx, limit: int = 50) -> list[SentRequest]:
    out = []
    for entry in ctx.audit.list(action="net.request", limit=limit):
        d = entry.details or {}
        out.append(
            SentRequest(
                ts=entry.ts,
                host=entry.target_id or "",
                purpose=str(d.get("purpose", "")),
                scheme=str(d.get("scheme", "")),
                path=str(d.get("path", "")),
                actor=entry.actor,
            )
        )
    return out


# ---------- watchlists ----------


class Watchlist(ApiModel):
    id: str
    kind: str
    target: str
    label: str
    interval_s: int
    enabled: bool
    created_at: str
    last_checked_at: str | None = None
    last_summary: str = ""
    unseen: int = 0


class WatchlistHit(ApiModel):
    id: str
    found_at: str
    summary: str
    detail: str
    seen: bool


class WatchlistCreate(BaseModel):
    kind: Literal["topic", "page"]
    target: str = Field(min_length=2, max_length=2000, description="A search query (topic) or a URL (page)")
    label: str = Field(default="", max_length=200)
    interval_s: int = Field(default=86400, ge=300, le=30 * 24 * 60 * 60)


class WatchlistPatch(BaseModel):
    enabled: bool


def _store(ctx: CoreContext) -> WatchlistStore:
    return WatchlistStore(ctx.dbs.universe)


def _to_model(store: WatchlistStore, row: sqlite3.Row) -> Watchlist:
    return Watchlist(
        id=row["id"],
        kind=row["kind"],
        target=row["target"],
        label=row["label"],
        interval_s=row["interval_s"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
        last_checked_at=row["last_checked_at"],
        last_summary=row["last_summary"],
        unseen=store.unseen_count(row["id"]),
    )


@router.get("/watchlists", response_model=list[Watchlist])
async def list_watchlists(ctx: Ctx) -> list[Watchlist]:
    store = _store(ctx)
    return [_to_model(store, row) for row in store.list()]


@router.post("/watchlists", response_model=Watchlist, status_code=status.HTTP_201_CREATED)
async def create_watchlist(ctx: Ctx, body: WatchlistCreate) -> Watchlist:
    if body.kind == "page" and not body.target.lower().startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "A page watchlist needs an http(s) URL")
    store = _store(ctx)
    row = store.create(kind=body.kind, target=body.target, label=body.label, interval_s=body.interval_s)
    ctx.audit.append(
        actor="user", action="setting.changed", target_type="watchlist", target_id=row["id"], details={"op": "add"}
    )
    return _to_model(store, row)


@router.patch("/watchlists/{watchlist_id}", response_model=Watchlist)
async def patch_watchlist(ctx: Ctx, watchlist_id: str, body: WatchlistPatch) -> Watchlist:
    store = _store(ctx)
    row = store.set_enabled(watchlist_id, body.enabled)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such watchlist")
    return _to_model(store, row)


@router.delete("/watchlists/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_watchlist(ctx: Ctx, watchlist_id: str) -> None:
    if not _store(ctx).delete(watchlist_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such watchlist")


@router.get("/watchlists/{watchlist_id}/hits", response_model=list[WatchlistHit])
async def watchlist_hits(ctx: Ctx, watchlist_id: str, limit: int = 50) -> list[WatchlistHit]:
    store = _store(ctx)
    if store.get(watchlist_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such watchlist")
    hits = [
        WatchlistHit(id=h["id"], found_at=h["found_at"], summary=h["summary"], detail=h["detail"], seen=bool(h["seen"]))
        for h in store.hits(watchlist_id, limit)
    ]
    store.mark_seen(watchlist_id)
    return hits


@router.post("/watchlists/{watchlist_id}/check", response_model=Watchlist)
async def check_watchlist(ctx: Ctx, watchlist_id: str) -> Watchlist:
    store = _store(ctx)
    row = store.get(watchlist_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such watchlist")
    try:
        await check_one(ctx, store, row)
    except EgressDenied as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except FetchRefused as exc:
        store.record_failure(watchlist_id, f"check failed: {exc}"[:500], utcnow())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"UNIVERSE couldn't check this: {exc}") from exc
    except (httpx.HTTPError, TimeoutError) as exc:
        why = "it took too long" if isinstance(exc, TimeoutError) else _http_reason(exc)
        store.record_failure(watchlist_id, f"check failed: {type(exc).__name__}", utcnow())
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"UNIVERSE couldn't check this: {why}") from exc
    refreshed = store.get(watchlist_id)
    assert refreshed is not None
    return _to_model(store, refreshed)


def _http_reason(exc: httpx.HTTPError) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"the site answered {exc.response.status_code}"
    return f"the site couldn't be reached ({type(exc).__name__})"
