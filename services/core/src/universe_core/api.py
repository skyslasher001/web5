"""REST API v1 (ARCHITECTURE.md §5.1, Phase 1 subset)."""

import os
import platform
from typing import Annotated, Any, Literal

import httpx
import psutil
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from universe_common.errors import MAX_MESSAGE, MAX_STACK, fingerprint_from_text
from universe_common.schema import ApiModel
from universe_core import __version__
from universe_core.chat import Conversation, Message
from universe_core.context import CoreContext
from universe_core.errors import ErrorRecord
from universe_core.events import Event
from universe_core.protected.audit import AuditEntry, AuditVerification
from universe_models.hardware import HardwareInfo
from universe_models.ollama import InstalledModel, OllamaStatus
from universe_models.recommend import Recommendation

_process = psutil.Process(os.getpid())
_process.cpu_percent(interval=None)  # prime: the first reading is always 0.0

# Every handler is `async def`: Core state (event-bus queues, asyncio tasks, the shared SQLite
# connections) may only be touched on the event-loop thread. FastAPI runs plain `def` handlers in a
# thread pool. tests/integration/test_core_threading.py enforces this.


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]


# ---------- schemas ----------


class Health(ApiModel):
    status: Literal["ok"] = "ok"
    service: Literal["core"] = "core"
    version: str
    safe_mode: bool
    pid: int


class WsTicket(ApiModel):
    ticket: str
    expires_in_s: float


class Vitals(ApiModel):
    version: str
    pid: int
    uptime_s: float
    rss_bytes: int
    cpu_percent: float
    python: str
    safe_mode: bool
    ws_clients: int
    event_seq: int
    db_bytes: dict[str, int]
    active_chats: int
    ollama: OllamaStatus


class Project(ApiModel):
    id: str
    name: str
    slug: str
    description: str
    status: str
    color_token: str
    layout_seed: int
    created_at: str
    item_count: int = 0


class AgentInfo(ApiModel):
    id: str
    name: str
    purpose: str
    color: str
    icon: str | None
    model: str
    permission_tier: str
    status: Literal["idle", "working", "disabled"]


class ModelsInfo(ApiModel):
    ollama: OllamaStatus
    installed: list[InstalledModel]
    assignments: dict[str, str]
    chat_model: str | None
    chat_model_error: str | None = None
    chat_model_hint: str | None = None


class AssignmentRequest(BaseModel):
    tier: Literal["local-fast", "local-large", "embed_text", "vision"]
    model: str = Field(min_length=1, max_length=200)


class ChatSendRequest(BaseModel):
    text: str = Field(min_length=1, max_length=20_000)
    conversation_id: str | None = None
    agent_id: str = "core"


class ChatSendResponse(ApiModel):
    conversation_id: str
    user_message_id: str
    assistant_message_id: str


class CancelResponse(ApiModel):
    cancelled: bool


class EventPage(ApiModel):
    events: list[Event]
    last_seq: int


class ErrorReport(BaseModel):
    service: Literal["renderer", "desktop"]
    kind: str = Field(min_length=1, max_length=200)
    message: str = Field(max_length=MAX_MESSAGE)
    stack: str = Field(default="", max_length=MAX_STACK)
    context: dict[str, Any] = Field(default_factory=dict)
    severity: Literal["warning", "error", "critical"] = "error"


TIER_CAPABILITY = {
    "local-fast": ("completion", "chat"),
    "local-large": ("completion", "chat"),
    "embed_text": ("embedding", "embedding"),
    "vision": ("vision", "vision"),
}


# ---------- routers ----------

public = APIRouter(prefix="/api/v1")
router = APIRouter(prefix="/api/v1")


@public.get("/health", response_model=Health)
async def health(ctx: Ctx) -> Health:
    return Health(version=__version__, safe_mode=ctx.settings.safe_mode, pid=ctx.pid)


@router.post("/session/ws-ticket", response_model=WsTicket)
async def ws_ticket(ctx: Ctx) -> WsTicket:
    return WsTicket(ticket=ctx.tickets.issue(), expires_in_s=ctx.tickets.ttl_s)


@router.get("/system/vitals", response_model=Vitals)
async def vitals(ctx: Ctx) -> Vitals:
    import time

    return Vitals(
        version=__version__,
        pid=ctx.pid,
        uptime_s=round(time.monotonic() - ctx.started, 1),
        rss_bytes=_process.memory_info().rss,
        cpu_percent=_process.cpu_percent(interval=None),
        python=platform.python_version(),
        safe_mode=ctx.settings.safe_mode,
        ws_clients=ctx.bus.subscriber_count,
        event_seq=ctx.bus.last_seq(),
        db_bytes=ctx.dbs.sizes(),
        active_chats=len(ctx.chat.active_conversations),
        ollama=await ctx.ollama.status(),
    )


@router.get("/system/hardware", response_model=HardwareInfo)
async def hardware(ctx: Ctx, refresh: bool = False) -> HardwareInfo:
    return await ctx.hardware(refresh=refresh)


@router.get("/models/recommendation", response_model=Recommendation)
async def model_recommendation(ctx: Ctx) -> Recommendation:
    return await ctx.recommendation()


@router.get("/models", response_model=ModelsInfo)
async def models(ctx: Ctx) -> ModelsInfo:
    from universe_agents.router import NoModelAvailable

    status_ = await ctx.ollama.status()
    installed: list[InstalledModel] = []
    if status_.reachable:
        try:
            installed = await ctx.ollama.list_models(refresh=True)
        except httpx.HTTPError as exc:
            status_ = OllamaStatus(reachable=False, url=status_.url, error=str(exc) or type(exc).__name__)
    info = ModelsInfo(ollama=status_, installed=installed, assignments=ctx.assignments(), chat_model=None)
    if not status_.reachable:
        # Don't name a model from a stale cache when Ollama can't list its models right now.
        info.chat_model_error = f"Ollama is not reachable at {status_.url}"
        info.chat_model_hint = "Start Ollama, or let UNIVERSE start it (System → Services)."
        return info
    try:
        info.chat_model = await ctx.router.resolve("local-fast")
    except NoModelAvailable as exc:
        info.chat_model_error, info.chat_model_hint = str(exc), exc.hint
    return info


@router.put("/models/assignments", response_model=ModelsInfo)
async def set_assignment(ctx: Ctx, body: AssignmentRequest) -> ModelsInfo:
    try:
        installed = await ctx.ollama.list_models(refresh=True)
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Ollama is not reachable") from exc
    needed, label = TIER_CAPABILITY[body.tier]
    names = {m.name for m in installed if needed in m.capabilities}
    if body.model not in names:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"'{body.model}' is not an installed {label} model")
    ctx.set_assignment(body.tier, body.model, actor="user")
    if body.tier == "embed_text" and ctx.governor is not None:
        await ctx.governor.check_embedder()  # re-embeds in the background with the new model
    return await models(ctx)


@router.delete("/models/assignments/{tier}", response_model=ModelsInfo)
async def clear_assignment(ctx: Ctx, tier: Literal["local-fast", "local-large", "embed_text", "vision"]) -> ModelsInfo:
    if ctx.clear_assignment(tier, actor="user") and tier == "embed_text" and ctx.governor is not None:
        await ctx.governor.check_embedder()
    return await models(ctx)


@router.get("/agents", response_model=list[AgentInfo])
async def agents(ctx: Ctx) -> list[AgentInfo]:
    out = []
    for agent in ctx.agents.values():
        if ctx.settings.safe_mode:
            state: Literal["idle", "working", "disabled"] = "disabled"
        else:
            state = "working" if ctx.chat.is_agent_busy(agent.id) else "idle"
        out.append(
            AgentInfo(
                id=agent.id,
                name=agent.name,
                purpose=agent.purpose,
                color=agent.color,
                icon=agent.icon,
                model=agent.model,
                permission_tier=agent.permission_tier,
                status=state,
            )
        )
    return out


@router.get("/projects", response_model=list[Project])
async def projects(ctx: Ctx) -> list[Project]:
    rows = ctx.dbs.universe.execute(
        "SELECT p.*, (SELECT COUNT(*) FROM item_projects ip JOIN items i ON i.id = ip.item_id"
        " WHERE ip.project_id = p.id AND i.trashed_at IS NULL) AS item_count"
        " FROM projects p ORDER BY p.layout_seed, p.created_at"
    )
    return [Project(**{k: r[k] for k in Project.model_fields}) for r in rows]


@router.post("/chat", response_model=ChatSendResponse, status_code=status.HTTP_202_ACCEPTED)
async def chat_send(ctx: Ctx, body: ChatSendRequest) -> ChatSendResponse:
    result = await ctx.chat.send(text=body.text, conversation_id=body.conversation_id, agent_id=body.agent_id)
    return ChatSendResponse(**result.__dict__)


@router.get("/conversations", response_model=list[Conversation])
async def conversations(ctx: Ctx, limit: int = Query(50, ge=1, le=500)) -> list[Conversation]:
    return ctx.chat.conversations(limit)


@router.get("/conversations/{conversation_id}/messages", response_model=list[Message])
async def conversation_messages(ctx: Ctx, conversation_id: str) -> list[Message]:
    return ctx.chat.messages(conversation_id)


@router.post("/conversations/{conversation_id}/cancel", response_model=CancelResponse)
async def cancel(ctx: Ctx, conversation_id: str) -> CancelResponse:
    return CancelResponse(cancelled=ctx.chat.cancel(conversation_id))


@router.get("/events", response_model=EventPage)
async def events(
    ctx: Ctx,
    since_seq: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=5000),
    type: Annotated[list[str] | None, Query()] = None,
    tail: int | None = Query(None, ge=1, le=500, description="Return the newest N events instead"),
) -> EventPage:
    events = ctx.bus.tail(tail) if tail else ctx.bus.replay(since_seq, limit=limit, types=type)
    return EventPage(events=events, last_seq=ctx.bus.last_seq())


@router.post("/errors", response_model=ErrorRecord | None, status_code=status.HTTP_201_CREATED)
async def report_error(ctx: Ctx, body: ErrorReport) -> ErrorRecord | None:
    return ctx.errors.record(
        service=body.service,
        kind=body.kind,
        message=body.message,
        stack=body.stack,
        fingerprint=fingerprint_from_text(body.kind, body.message, body.stack),
        context=body.context,
        severity=body.severity,
    )


@router.get("/errors", response_model=list[ErrorRecord])
async def list_errors(ctx: Ctx, limit: int = Query(100, ge=1, le=1000)) -> list[ErrorRecord]:
    return ctx.errors.list(limit=limit)


@router.get("/audit", response_model=list[AuditEntry])
async def audit(ctx: Ctx, limit: int = Query(100, ge=1, le=1000), action: str | None = None) -> list[AuditEntry]:
    return ctx.audit.list(limit=limit, action=action)


@router.get("/audit/verify", response_model=AuditVerification)
async def audit_verify(ctx: Ctx) -> AuditVerification:
    return ctx.audit.verify()
