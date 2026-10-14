"""REST for the agent engine (ARCHITECTURE.md §5.1): the agent roster, tasks, approvals, memories, permissions,
budget, kill switch.

Permission rules, budget caps and the kill switch belong to the protected policy engine; until the owner
applies the Phase 3 protected-core patch those endpoints answer 503 with the reason.
"""

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from universe_agents.registry import AgentConfigError
from universe_common.schema import ApiModel
from universe_core.agent_engine import AgentEngine, AgentTask, Approval, EngineUnavailable, TaskDetail
from universe_core.agent_roster import AgentRoster, AgentStats
from universe_core.context import CoreContext
from universe_core.mcp_client import MCPManager, MCPServerInfo, MCPServerRequest
from universe_core.memory import Memory

router = APIRouter(prefix="/api/v1")


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]


def _engine(ctx: CoreContext) -> AgentEngine:
    if ctx.engine is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agent engine is not running")
    return ctx.engine


def _safety(ctx: CoreContext) -> Any:
    if ctx.safety is None:
        reason = ctx.engine.unavailable_reason if ctx.engine is not None else None
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, reason or "The policy engine is not installed")
    return ctx.safety


class EngineStatus(ApiModel):
    available: bool
    reason: str | None
    tools: list[str]
    killswitch_engaged: bool
    pending_approvals: int


class RunRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=20_000)


class RunResponse(ApiModel):
    task_id: str


class DecisionRequest(BaseModel):
    approve: bool
    remember: bool = False  # approve: also allow this tool for this agent from now on (a permission rule)


class MemoryDecision(BaseModel):
    approve: bool


class MemoryPatch(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class MemoryCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    scope: str = Field(default="self", pattern=r"^(self|shared|agent:[a-z][a-z0-9-]{1,31})$")
    type: Literal["episodic", "semantic", "procedural"] = "semantic"


class KillSwitchRequest(BaseModel):
    engaged: bool


class KillSwitchStatus(ApiModel):
    available: bool
    engaged: bool
    since: str | None = None
    via: str | None = None


@router.get("/engine", response_model=EngineStatus)
async def engine_status(ctx: Ctx) -> EngineStatus:
    engine = _engine(ctx)
    killswitch = getattr(ctx.safety, "killswitch", None)
    return EngineStatus(
        available=engine.available,
        reason=engine.unavailable_reason,
        tools=ctx.tools.names(),
        killswitch_engaged=bool(killswitch and killswitch.engaged),
        pending_approvals=len(engine.approvals("pending")),
    )


# ---------- the roster (Agents tab): synopsis, stats, adding, turning off, removing ----------


class AgentStatsOut(ApiModel):
    tasks: int
    done: int
    failed: int
    cancelled: int
    success_rate: float | None
    tokens_in: int
    tokens_out: int
    cost_usd: float
    avg_steps: float | None
    last_active: str | None


class AgentProfile(ApiModel):
    id: str
    name: str
    purpose: str
    synopsis: str
    color: str
    icon: str | None
    model: str
    permission_tier: str
    tools: list[str]
    origin: Literal["built-in", "custom"]
    enabled: bool
    busy: bool
    locked_reason: str | None
    stats: AgentStatsOut


class AgentCreate(BaseModel):
    name: str = Field(min_length=2, max_length=40)
    purpose: str = Field(min_length=3, max_length=200)
    synopsis: str = Field(default="", max_length=1200)
    instructions: str = Field(min_length=10, max_length=8000)  # its system prompt
    color: str = Field(default="cyan", pattern=r"^(cyan|violet|amber|rose|green|blue|slate|#[0-9A-Fa-f]{6})$")
    tools: list[str] = Field(default_factory=list, max_length=40)
    permission_tier: Literal["read", "write"] = "read"
    model: Literal["local-fast", "local-large"] = "local-fast"
    max_steps: int = Field(default=12, ge=1, le=40)


class AgentPatch(BaseModel):
    enabled: bool | None = None
    synopsis: str | None = Field(default=None, max_length=1200)


def _roster(ctx: CoreContext) -> AgentRoster:
    if ctx.roster is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The agent roster isn't loaded")
    return ctx.roster


def _busy(ctx: CoreContext, agent_id: str) -> bool:
    return ctx.chat.is_agent_busy(agent_id) or (ctx.engine is not None and ctx.engine.busy(agent_id))


def _profiles(ctx: CoreContext) -> list[AgentProfile]:
    roster = _roster(ctx)
    stats = roster.stats()
    out = []
    for e in roster.entries():
        a, st = e.agent, stats.get(e.agent.id, AgentStats())
        out.append(
            AgentProfile(
                id=a.id,
                name=a.name,
                purpose=a.purpose,
                synopsis=a.synopsis,
                color=a.color,
                icon=a.icon,
                model=a.model,
                permission_tier=a.permission_tier,
                tools=a.tools,
                origin="custom" if e.origin == "custom" else "built-in",
                enabled=e.enabled,
                busy=_busy(ctx, a.id),
                locked_reason=e.locked_reason,
                stats=AgentStatsOut(
                    tasks=st.tasks,
                    done=st.done,
                    failed=st.failed,
                    cancelled=st.cancelled,
                    success_rate=st.success_rate,
                    tokens_in=st.tokens_in,
                    tokens_out=st.tokens_out,
                    cost_usd=st.cost_usd,
                    avg_steps=st.avg_steps,
                    last_active=st.last_active,
                ),
            )
        )
    return out


def _profile(ctx: CoreContext, agent_id: str) -> AgentProfile:
    for p in _profiles(ctx):
        if p.id == agent_id:
            return p
    raise HTTPException(status.HTTP_404_NOT_FOUND, f"No agent called '{agent_id}'")


@router.get("/agents/roster", response_model=list[AgentProfile])
async def agent_roster(ctx: Ctx) -> list[AgentProfile]:
    return _profiles(ctx)


@router.post("/agents", response_model=AgentProfile, status_code=status.HTTP_201_CREATED)
async def add_agent(ctx: Ctx, body: AgentCreate) -> AgentProfile:
    try:
        agent = _roster(ctx).create(**body.model_dump(), known_tools=set(ctx.tools.names()))
    except (ValueError, AgentConfigError) as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    details = {"tools": agent.tools, "permission_tier": agent.permission_tier}
    ctx.audit.append(actor="user", action="agent.added", target_type="agent", target_id=agent.id, details=details)
    ctx.bus.publish("agent.added", {"agent_id": agent.id, "name": agent.name}, actor="user")
    return _profile(ctx, agent.id)


@router.patch("/agents/{agent_id}", response_model=AgentProfile)
async def update_agent(ctx: Ctx, agent_id: str, body: AgentPatch) -> AgentProfile:
    roster = _roster(ctx)
    try:
        roster.entry(agent_id)
        if body.enabled is False and _busy(ctx, agent_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "It's working on a task: wait or cancel the task first")
        if body.enabled is not None:
            roster.set_enabled(agent_id, body.enabled)
        if body.synopsis is not None:
            roster.set_synopsis(agent_id, body.synopsis)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    changed = {"enabled": body.enabled} if body.enabled is not None else {}
    if body.synopsis is not None:
        changed["synopsis_edited"] = True
    ctx.audit.append(actor="user", action="agent.updated", target_type="agent", target_id=agent_id, details=changed)
    ctx.bus.publish("agent.updated", {"agent_id": agent_id, **changed}, actor="user")
    return _profile(ctx, agent_id)


@router.delete("/agents/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_agent(ctx: Ctx, agent_id: str) -> None:
    roster = _roster(ctx)
    try:
        roster.entry(agent_id)
        if _busy(ctx, agent_id):
            raise HTTPException(status.HTTP_409_CONFLICT, "It's working on a task: wait or cancel the task first")
        kept = roster.remove(agent_id)
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    details = {"kept_in": str(kept)}
    ctx.audit.append(actor="user", action="agent.removed", target_type="agent", target_id=agent_id, details=details)
    ctx.bus.publish("agent.removed", {"agent_id": agent_id}, actor="user")


# ---------- tasks ----------


@router.post("/agents/{agent_id}/run", response_model=RunResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_agent(ctx: Ctx, agent_id: str, body: RunRequest) -> RunResponse:
    engine = _engine(ctx)
    try:
        return RunResponse(task_id=engine.start(agent_id, body.instruction))
    except EngineUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/tasks", response_model=list[AgentTask])
async def list_tasks(
    ctx: Ctx,
    agent: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    limit: int = 50,
    all_levels: bool = False,
) -> list[AgentTask]:
    return _engine(ctx).tasks(agent=agent, status=status_, top_level=not all_levels, limit=limit)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(ctx: Ctx, task_id: str) -> TaskDetail:
    detail = _engine(ctx).detail(task_id)
    if detail is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such task")
    return detail


@router.post("/tasks/{task_id}/cancel", response_model=AgentTask)
async def cancel_task(ctx: Ctx, task_id: str) -> AgentTask:
    engine = _engine(ctx)
    if engine.task(task_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such task")
    engine.cancel(task_id)
    task = engine.task(task_id)
    assert task is not None
    return task


# ---------- approvals ----------


@router.get("/approvals", response_model=list[Approval])
async def list_approvals(
    ctx: Ctx, status_: Annotated[str | None, Query(alias="status")] = "pending", limit: int = 100
) -> list[Approval]:
    return _engine(ctx).approvals(status_ or None, limit)


@router.post("/approvals/{approval_id}/decision", response_model=Approval)
async def decide_approval(ctx: Ctx, approval_id: str, body: DecisionRequest) -> Approval:
    engine = _engine(ctx)
    pending = next((a for a in engine.approvals("pending") if a.id == approval_id), None)
    if body.approve and body.remember and pending is not None and pending.tool:
        agent_id = pending.requester.removeprefix("agent:")
        _safety(ctx).permissions.add_from({"agent_id": agent_id, "tool": pending.tool, "decision": "allow"})
    approval = engine.decide(approval_id, body.approve, via="ui")
    if approval is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such approval")
    return approval


# ---------- memory ----------


@router.get("/memories", response_model=list[Memory])
async def list_memories(
    ctx: Ctx,
    scope: str | None = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
    q: str | None = None,
    limit: int = 100,
) -> list[Memory]:
    return ctx.memory.browse(scope=scope, status=status_, q=q, limit=limit)


@router.post("/memories", response_model=Memory, status_code=status.HTTP_201_CREATED)
async def create_memory(ctx: Ctx, body: MemoryCreate) -> Memory:
    memory = ctx.memory.save(content=body.content, scope=body.scope, type=body.type, created_by="user")
    ctx.bus.publish(
        "memory.created",
        {"memory_id": memory.id, "scope": memory.scope},
        actor="user",
        subject_type="memory",
        subject_id=memory.id,
    )
    return memory


@router.post("/memories/{memory_id}/decision", response_model=Memory)
async def decide_memory(ctx: Ctx, memory_id: str, body: MemoryDecision) -> Memory:
    memory = ctx.memory.decide(memory_id, body.approve)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No proposed memory with that id")
    ctx.audit.append(
        actor="user",
        action="approval.decided",
        target_type="memory",
        target_id=memory_id,
        details={"approved": body.approve, "kind": "memory_update"},
    )
    ctx.bus.publish(
        "memory.updated" if body.approve else "memory.deleted",
        {"memory_id": memory_id},
        actor="user",
        subject_type="memory",
        subject_id=memory_id,
    )
    return memory


@router.patch("/memories/{memory_id}", response_model=Memory)
async def edit_memory(ctx: Ctx, memory_id: str, body: MemoryPatch) -> Memory:
    memory = ctx.memory.update(memory_id, body.content)
    if memory is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such memory")
    ctx.bus.publish(
        "memory.updated", {"memory_id": memory_id}, actor="user", subject_type="memory", subject_id=memory_id
    )
    return memory


@router.delete("/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(ctx: Ctx, memory_id: str) -> None:
    if not ctx.memory.delete(memory_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such memory")
    ctx.audit.append(actor="user", action="purge", target_type="memory", target_id=memory_id, details={})
    ctx.bus.publish(
        "memory.deleted", {"memory_id": memory_id}, actor="user", subject_type="memory", subject_id=memory_id
    )


# ---------- permissions, budget, kill switch (protected engine) ----------


@router.get("/permissions/rules")
async def list_rules(ctx: Ctx) -> list[dict[str, Any]]:
    return [r.model_dump() for r in _safety(ctx).permissions.list()]


@router.post("/permissions/rules", status_code=status.HTTP_201_CREATED)
async def add_rule(ctx: Ctx, body: dict[str, Any]) -> dict[str, Any]:
    safety = _safety(ctx)
    try:
        return safety.permissions.add_from(body).model_dump()
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc


@router.delete("/permissions/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_rule(ctx: Ctx, rule_id: str) -> None:
    if not _safety(ctx).permissions.remove(rule_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such rule")


@router.get("/budget")
async def budget(ctx: Ctx) -> dict[str, Any]:
    return _safety(ctx).budget.status().model_dump()


@router.put("/budget/caps")
async def set_budget_caps(ctx: Ctx, body: dict[str, Any]) -> dict[str, Any]:
    safety = _safety(ctx)
    try:
        safety.budget.set_caps_from(body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    return safety.budget.status().model_dump()


@router.get("/killswitch", response_model=KillSwitchStatus)
async def killswitch_status(ctx: Ctx) -> KillSwitchStatus:
    if ctx.safety is None:
        return KillSwitchStatus(available=False, engaged=False)
    return KillSwitchStatus(available=True, **_safety(ctx).killswitch.status())


@router.post("/killswitch", response_model=KillSwitchStatus)
async def engage_killswitch(ctx: Ctx, body: KillSwitchRequest) -> KillSwitchStatus:
    """Engaging from the HUD is always allowed. Releasing goes through Electron main and the supervisor."""
    safety = _safety(ctx)
    if not body.engaged:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Release the kill switch from the app's control (tray, hotkey or HUD button)"
        )
    safety.killswitch.set(True, via="hud")
    return KillSwitchStatus(available=True, **safety.killswitch.status())


@router.post("/killswitch/sync", response_model=KillSwitchStatus)
async def sync_killswitch(ctx: Ctx) -> KillSwitchStatus:
    """The supervisor changed the state file: apply it now."""
    safety = _safety(ctx)
    safety.killswitch.sync(actor="user")
    return KillSwitchStatus(available=True, **safety.killswitch.status())


# ---------- MCP servers ----------


class EnabledRequest(BaseModel):
    enabled: bool


def _mcp(ctx: CoreContext) -> MCPManager:
    if ctx.mcp is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "MCP is not available")
    return ctx.mcp


@router.get("/mcp/servers", response_model=list[MCPServerInfo])
async def list_mcp_servers(ctx: Ctx) -> list[MCPServerInfo]:
    return _mcp(ctx).list()


@router.post("/mcp/servers", response_model=MCPServerInfo, status_code=status.HTTP_201_CREATED)
async def add_mcp_server(ctx: Ctx, body: MCPServerRequest) -> MCPServerInfo:
    """Adds a program for UNIVERSE to run: only from your UI session (it carries the session token)."""
    try:
        return await _mcp(ctx).add(body)
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc


@router.post("/mcp/servers/{server_id}/enabled", response_model=MCPServerInfo)
async def enable_mcp_server(ctx: Ctx, server_id: str, body: EnabledRequest) -> MCPServerInfo:
    info = await _mcp(ctx).set_enabled(server_id, body.enabled)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such MCP server")
    return info


@router.post("/mcp/servers/{server_id}/restart", response_model=MCPServerInfo)
async def restart_mcp_server(ctx: Ctx, server_id: str) -> MCPServerInfo:
    info = await _mcp(ctx).restart(server_id)
    if info is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such MCP server")
    return info


@router.delete("/mcp/servers/{server_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_mcp_server(ctx: Ctx, server_id: str) -> None:
    if not await _mcp(ctx).remove(server_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No such MCP server")
