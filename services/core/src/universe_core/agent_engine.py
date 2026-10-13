"""Core's side of the agent engine (ADR-0011): tasks, traces, approvals, delegation and Critic review.

The loop itself is `universe_agents.runtime`. This module stores what it does (`agent_tasks`, `task_steps`,
`approvals`, `usage_ledger`), parks tasks on approvals until you decide, emits events and writes the audit
log. Everything here runs on Core's event loop.
"""

import asyncio
import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from universe_agents.registry import AgentDefinition
from universe_agents.runtime import AgentRuntime, Decision, Outcome, TaskFailed, TaskState
from universe_agents.tools import Tool, ToolContext, ToolResult
from universe_common.errors import capture_exception
from universe_common.ids import uuid7
from universe_common.log import get_logger
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_core.errors import ErrorStore
from universe_core.events import EventBus
from universe_core.memory import MemoryStore, scopes_for
from universe_core.protected.audit import AuditWriter

log = get_logger(__name__)

APPROVAL_TTL = timedelta(hours=24)
MAX_DEPTH = 1  # Core → specialist; specialists don't delegate further
TaskStatus = Literal["queued", "running", "waiting_approval", "done", "failed", "cancelled"]


class AgentTask(ApiModel):
    id: str
    parent_id: str | None
    conversation_id: str | None
    agent_id: str
    title: str
    input: str
    output: str | None
    status: TaskStatus
    steps_used: int
    tokens_in: int
    tokens_out: int
    cost_usd: float
    model: str | None
    tainted: bool
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class TaskStep(ApiModel):
    id: str
    task_id: str
    n: int
    kind: str
    model: str | None
    tool: str | None
    args: str
    result: str | None
    decision: str | None
    tokens: int
    duration_ms: int
    created_at: str


class TaskDetail(ApiModel):
    task: AgentTask
    steps: list[TaskStep]
    children: list[AgentTask]


class Approval(ApiModel):
    id: str
    kind: Literal["tool_call", "memory_update", "budget_raise"]
    requester: str
    task_id: str | None
    tool: str | None
    args: dict[str, Any]
    risk: Literal["low", "medium", "high"]
    summary: str
    reason: str
    status: Literal["pending", "approved", "denied", "expired", "auto_approved"]
    decided_via: str | None
    created_at: str
    decided_at: str | None
    expires_at: str


def _task(row: sqlite3.Row) -> AgentTask:
    data = {k: row[k] for k in AgentTask.model_fields}
    data["tainted"] = bool(row["tainted"])
    return AgentTask(**data)


def _approval(row: sqlite3.Row) -> Approval:
    data = {k: row[k] for k in Approval.model_fields}
    data["args"] = json.loads(row["args"] or "{}")
    return Approval(**data)


class DelegateArgs(BaseModel):
    agent: str = Field(description="Which specialist: navigator, librarian, scribe or critic")
    instruction: str = Field(min_length=1, max_length=4000, description="What they should do, with all needed detail")


class EngineUnavailable(RuntimeError):
    """Agents can't run tools right now (no policy engine, safe mode). User-presentable."""


class AgentEngine:
    def __init__(
        self,
        conn: sqlite3.Connection,
        bus: EventBus,
        audit: AuditWriter,
        agents: dict[str, AgentDefinition],
        memory: MemoryStore,
        errors: ErrorStore,
        runtime: AgentRuntime | None,
        *,
        unavailable_reason: str | None = None,
    ) -> None:
        self._conn = conn
        self._bus = bus
        self._audit = audit
        self.agents = agents
        self.memory = memory
        self._errors = errors
        self.runtime = runtime
        self.unavailable_reason = unavailable_reason if runtime is None else None
        self._running: dict[str, asyncio.Task[Any]] = {}
        self._waiting: dict[str, asyncio.Future[bool]] = {}
        self._step_n: dict[str, int] = {}
        self.failure_codes: dict[str, str] = {}  # task id → why it failed ("provider", "policy"…), for callers

    @property
    def available(self) -> bool:
        return self.runtime is not None

    def delegate_tool(self) -> Tool:
        async def run(args: BaseModel, ctx: ToolContext) -> ToolResult:
            assert isinstance(args, DelegateArgs)
            return await self._delegate(args, ctx)

        return Tool(
            name="agent.delegate",
            description=(
                "Hand a subtask to a specialist and get their answer back. navigator: moves around the vault and "
                "galaxies; librarian: finds and reads your notes and files; scribe: writes summaries and notes; "
                "critic: reviews a result."
            ),
            input_model=DelegateArgs,
            tier="read",  # delegating does nothing by itself; the specialist's own tool calls are each checked
            run=run,
            timeout_s=900,
            summarize=lambda a: f"Ask {getattr(a, 'agent', '?')} to: {getattr(a, 'instruction', '')[:120]}",
        )

    # ---------- lifecycle ----------

    def recover_after_restart(self) -> None:
        """Tasks don't survive a restart (ADR-0011 §3): say so instead of leaving them 'running' forever."""
        now = utcnow()
        self._conn.execute(
            "UPDATE agent_tasks SET status = 'failed', error = 'Interrupted by a restart of Core', finished_at = ?"
            " WHERE status IN ('queued', 'running', 'waiting_approval')",
            (now,),
        )
        self._conn.execute("UPDATE approvals SET status = 'expired', decided_at = ? WHERE status = 'pending'", (now,))

    async def shutdown(self) -> None:
        tasks = list(self._running.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def halt_all(self, reason: str) -> int:
        """Kill switch: cancel every running task and refuse every pending approval."""
        for approval_id, future in list(self._waiting.items()):
            if not future.done():
                future.set_result(False)
            self._set_approval(approval_id, "denied", via="rule", reason=reason)
        count = 0
        for task in list(self._running.values()):
            if not task.done():
                task.cancel()
                count += 1
        return count

    # ---------- tasks ----------

    def _new_task(
        self,
        agent: AgentDefinition,
        instruction: str,
        *,
        parent: TaskState | None,
        conversation_id: str | None,
        correlation_id: str | None,
    ) -> TaskState:
        task_id = uuid7()
        self._conn.execute(
            "INSERT INTO agent_tasks (id, parent_id, conversation_id, agent_id, title, input, status, correlation_id,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, 'queued', ?, ?)",
            (
                task_id,
                parent.task_id if parent else None,
                conversation_id,
                agent.id,
                instruction.splitlines()[0][:80] if instruction.strip() else agent.name,
                instruction,
                correlation_id,
                utcnow(),
            ),
        )
        # A specialist working for a tainted task starts tainted: what it was told came from untrusted text.
        return TaskState(
            task_id=task_id,
            agent_id=agent.id,
            parent_id=parent.task_id if parent else None,
            tainted=bool(parent and parent.tainted),
        )

    def _agent(self, agent_id: str) -> AgentDefinition:
        if self.runtime is None:
            raise EngineUnavailable(self.unavailable_reason or "The agent engine is not available")
        agent = self.agents.get(agent_id)
        if agent is None:
            raise ValueError(f"Unknown agent '{agent_id}'")
        return agent

    async def run(
        self,
        agent_id: str,
        instruction: str,
        *,
        conversation_id: str | None = None,
        history: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
        correlation_id: str | None = None,
        parent: TaskState | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> tuple[AgentTask, Outcome | None]:
        """Run a task to the end and return it. Task failures don't raise: they're in the task row.

        `on_started` runs right after `agent.started` is published (chat publishes `chat.started` there).
        """
        agent = self._agent(agent_id)
        state = self._new_task(
            agent, instruction, parent=parent, conversation_id=conversation_id, correlation_id=correlation_id
        )
        return await self._execute(
            agent,
            state,
            instruction,
            conversation_id=conversation_id,
            history=history,
            on_token=on_token,
            parent=parent,
            on_started=on_started,
        )

    def start(self, agent_id: str, instruction: str, *, conversation_id: str | None = None) -> str:
        """Run a task in the background; returns its id at once (POST /agents/{id}/run)."""
        agent = self._agent(agent_id)
        state = self._new_task(agent, instruction, parent=None, conversation_id=conversation_id, correlation_id=None)
        background = asyncio.create_task(
            self._execute(agent, state, instruction, conversation_id=conversation_id), name=f"agent:{agent.id}"
        )
        self._running[state.task_id] = background
        background.add_done_callback(lambda t: None if t.cancelled() else t.exception())
        return state.task_id

    async def _execute(
        self,
        agent: AgentDefinition,
        state: TaskState,
        instruction: str,
        *,
        conversation_id: str | None,
        history: list[dict[str, Any]] | None = None,
        on_token: Callable[[str], None] | None = None,
        parent: TaskState | None = None,
        on_started: Callable[[], None] | None = None,
    ) -> tuple[AgentTask, Outcome | None]:
        assert self.runtime is not None
        current = asyncio.current_task()
        if current is not None and state.task_id not in self._running:
            self._running[state.task_id] = current
        hooks = _Hooks(self, conversation_id)
        self._conn.execute("UPDATE agent_tasks SET started_at = ? WHERE id = ?", (utcnow(), state.task_id))
        hooks.emit(
            state,
            "agent.started",
            {"agent_id": agent.id, "conversation_id": conversation_id, "parent_id": state.parent_id},
        )
        self._audit.append(
            actor=f"agent:{agent.id}",
            action="task.started",
            target_type="task",
            target_id=state.task_id,
            details={"parent_id": state.parent_id},
            task_id=state.task_id,
        )
        if on_started is not None:
            on_started()
        outcome: Outcome | None = None
        try:
            outcome = await self.runtime.run(agent, state, instruction, hooks, history=history, on_token=on_token)
            output = outcome.output
            if state.used_side_effects and agent.id != "critic" and parent is None and "critic" in self.agents:
                output = await self._review(state, instruction, output, hooks)
                outcome.output = output
            self._finish(state, "done", output=output)
            hooks.emit(
                state, "agent.completed", {"agent_id": agent.id, "steps": state.steps_used, "tokens": state.tokens}
            )
        except asyncio.CancelledError:
            self._finish(state, "cancelled", error="Stopped")
            hooks.emit(state, "agent.completed", {"agent_id": agent.id, "cancelled": True})
            raise
        except TaskFailed as exc:
            self._remember_failure(state.task_id, exc.code)
            self._finish(state, "failed", error=str(exc))
            hooks.emit(state, "agent.failed", {"agent_id": agent.id, "code": exc.code, "error": str(exc)})
        except Exception as exc:
            captured = capture_exception(exc, {"task_id": state.task_id, "agent": agent.id})
            self._errors.record(
                service="core",
                kind=captured.kind,
                message=captured.message,
                stack=captured.stack,
                fingerprint=captured.fingerprint,
                context=captured.context,
            )
            log.exception("agent_task_failed", task_id=state.task_id)
            self._remember_failure(state.task_id, "internal")
            self._finish(state, "failed", error="Something went wrong; the error was recorded.")
            hooks.emit(state, "agent.failed", {"agent_id": agent.id, "code": "internal", "error": captured.message})
        finally:
            self._running.pop(state.task_id, None)
            self._step_n.pop(state.task_id, None)
        task = self.task(state.task_id)
        assert task is not None
        return task, outcome

    def _remember_failure(self, task_id: str, code: str) -> None:
        self.failure_codes[task_id] = code
        while len(self.failure_codes) > 200:  # only the caller that's waiting reads it; keep the map small
            self.failure_codes.pop(next(iter(self.failure_codes)))

    def cancel(self, task_id: str) -> bool:
        task = self._running.get(task_id)
        if task is None or task.done():
            return False
        task.cancel()
        return True

    def _finish(
        self, state: TaskState, status: TaskStatus, *, output: str | None = None, error: str | None = None
    ) -> None:
        self._conn.execute(
            "UPDATE agent_tasks SET status = ?, output = ?, error = ?, steps_used = ?, tokens_in = ?, tokens_out = ?,"
            " cost_usd = ?, tainted = ?, finished_at = ? WHERE id = ?",
            (
                status,
                output,
                error,
                state.steps_used,
                state.tokens_in,
                state.tokens_out,
                state.cost_usd,
                int(state.tainted),
                utcnow(),
                state.task_id,
            ),
        )
        self._audit.append(
            actor=f"agent:{state.agent_id}",
            action="task.finished",
            target_type="task",
            target_id=state.task_id,
            details={"status": status, "steps": state.steps_used},
            outcome="ok" if status == "done" else status,
            task_id=state.task_id,
        )

    async def _delegate(self, args: DelegateArgs, ctx: ToolContext) -> ToolResult:
        parent = self._state_for(ctx)
        if parent.parent_id is not None:
            return ToolResult("Error: specialists can't delegate further. Do the work yourself.", error=True)
        target = args.agent.strip().lower()
        if target not in self.agents or target == ctx.agent_id:
            names = ", ".join(sorted(a for a in self.agents if a != ctx.agent_id))
            return ToolResult(f"Error: no specialist named '{args.agent}'. Choose one of: {names}", error=True)
        hooks = _Hooks(self, None)
        hooks.step(parent, "delegate", tool="agent.delegate", args=json.dumps({"agent": target}))
        self._bus.publish(
            "agent.message",
            {"from": ctx.agent_id, "to": target, "task_id": ctx.task_id},
            actor=ctx.actor,
            subject_type="task",
            subject_id=ctx.task_id,
        )
        child, _outcome = await self.run(target, args.instruction, parent=parent)
        if child.tainted:
            parent.tainted = True
        if child.status != "done":
            return ToolResult(f"{target} could not finish: {child.error}", data={"task_id": child.id}, error=True)
        return ToolResult(
            child.output or "(no answer)", data={"task_id": child.id, "agent": target}, untrusted=child.tainted
        )

    async def _review(self, state: TaskState, instruction: str, output: str, hooks: "_Hooks") -> str:
        actions = [
            f"- {r['tool']}: {r['decision']}"
            for r in self._conn.execute(
                "SELECT tool, decision FROM task_steps WHERE task_id = ? AND kind = 'tool_call' ORDER BY n",
                (state.task_id,),
            )
        ]
        prompt = (
            f"Review this result before it goes to the user.\n\nRequest:\n{instruction}\n\n"
            f"Actions taken:\n{chr(10).join(actions) or '- none'}\n\nResult:\n{output}\n\n"
            "Reply 'OK' if it's accurate and complete, otherwise list the problems briefly."
        )
        review, _ = await self.run("critic", prompt, parent=state)
        verdict = (review.output or review.error or "").strip()
        hooks.step(state, "review", tool="critic", result=json.dumps({"task_id": review.id, "verdict": verdict[:2000]}))
        if review.status != "done" or not verdict:
            return output
        if verdict.upper().startswith("OK"):
            return f"{output}\n\n— Checked by Critic."
        return f"{output}\n\n— Critic's notes: {verdict}"

    def _state_for(self, ctx: ToolContext) -> TaskState:
        row = self._conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (ctx.task_id,)).fetchone()
        return TaskState(
            task_id=ctx.task_id, agent_id=ctx.agent_id, parent_id=row["parent_id"] if row else None, tainted=ctx.tainted
        )

    # ---------- approvals ----------

    async def ask(
        self, state: TaskState, agent: AgentDefinition, tool: Tool, args: BaseModel, decision: Decision
    ) -> bool:
        approval_id = uuid7()
        now = datetime.now(UTC)
        expires = now + APPROVAL_TTL
        summary = tool.describe(args)
        self._conn.execute(
            "INSERT INTO approvals (id, kind, requester, task_id, tool, args, risk, summary, reason, status,"
            " created_at, expires_at) VALUES (?, 'tool_call', ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)",
            (
                approval_id,
                f"agent:{agent.id}",
                state.task_id,
                tool.name,
                args.model_dump_json(),
                decision.risk,
                summary[:500],
                decision.reason[:500],
                _iso(now),
                _iso(expires),
            ),
        )
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._waiting[approval_id] = future
        self._bus.publish(
            "approval.requested",
            {
                "approval_id": approval_id,
                "agent_id": agent.id,
                "tool": tool.name,
                "risk": decision.risk,
                "summary": summary[:500],
                "task_id": state.task_id,
            },
            actor=f"agent:{agent.id}",
            subject_type="approval",
            subject_id=approval_id,
        )
        try:
            return await asyncio.wait_for(future, timeout=APPROVAL_TTL.total_seconds())
        except TimeoutError:
            self._set_approval(approval_id, "expired", via=None)
            self._bus.publish(
                "approval.expired",
                {"approval_id": approval_id},
                actor="system",
                subject_type="approval",
                subject_id=approval_id,
            )
            return False
        finally:
            self._waiting.pop(approval_id, None)

    def decide(self, approval_id: str, approve: bool, *, via: str = "ui") -> Approval | None:
        row = self._conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        if row is None:
            return None
        if row["status"] != "pending":
            return _approval(row)
        status = "approved" if approve else "denied"
        self._set_approval(approval_id, status, via=via)
        future = self._waiting.get(approval_id)
        if future is not None and not future.done():
            future.set_result(approve)
        elif future is None and row["kind"] == "tool_call":
            # Nobody is waiting (Core restarted since): nothing will run, so record it as expired instead.
            self._set_approval(approval_id, "expired", via=via)
        self._audit.append(
            actor="user",
            action="approval.decided",
            target_type="approval",
            target_id=approval_id,
            details={"tool": row["tool"], "approved": approve, "via": via},
            task_id=row["task_id"],
        )
        self._bus.publish(
            "approval.decided",
            {"approval_id": approval_id, "approved": approve, "tool": row["tool"]},
            actor="user",
            subject_type="approval",
            subject_id=approval_id,
        )
        updated = self._conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return _approval(updated)

    def _set_approval(self, approval_id: str, status: str, *, via: str | None, reason: str | None = None) -> None:
        self._conn.execute(
            "UPDATE approvals SET status = ?, decided_via = ?, decided_at = ?, reason = COALESCE(?, reason)"
            " WHERE id = ? AND status = 'pending'",
            (status, via, utcnow(), reason, approval_id),
        )

    def approvals(self, status: str | None = "pending", limit: int = 100) -> list[Approval]:
        if status:
            rows = self._conn.execute(
                "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC LIMIT ?", (status, min(limit, 500))
            )
        else:
            rows = self._conn.execute("SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (min(limit, 500),))
        return [_approval(r) for r in rows]

    # ---------- queries ----------

    def task(self, task_id: str) -> AgentTask | None:
        row = self._conn.execute("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)).fetchone()
        return _task(row) if row else None

    def detail(self, task_id: str) -> TaskDetail | None:
        task = self.task(task_id)
        if task is None:
            return None
        steps = [
            TaskStep(**{k: r[k] for k in TaskStep.model_fields})
            for r in self._conn.execute("SELECT * FROM task_steps WHERE task_id = ? ORDER BY n", (task_id,))
        ]
        children = [
            _task(r)
            for r in self._conn.execute("SELECT * FROM agent_tasks WHERE parent_id = ? ORDER BY created_at", (task_id,))
        ]
        return TaskDetail(task=task, steps=steps, children=children)

    def tasks(
        self, *, agent: str | None = None, status: str | None = None, top_level: bool = True, limit: int = 50
    ) -> list[AgentTask]:
        sql, params = "SELECT * FROM agent_tasks WHERE 1 = 1", []
        if top_level:
            sql += " AND parent_id IS NULL"
        if agent:
            sql += " AND agent_id = ?"
            params.append(agent)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(min(limit, 500))
        return [_task(r) for r in self._conn.execute(sql, params)]

    def busy(self, agent_id: str) -> bool:
        return any(
            row["agent_id"] == agent_id
            for row in self._conn.execute(
                "SELECT agent_id FROM agent_tasks WHERE status IN ('running', 'waiting_approval')"
            )
        )


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class _Hooks:
    """TaskHooks for the runtime: Core's stores, events, audit and memory."""

    def __init__(self, engine: AgentEngine, conversation_id: str | None) -> None:
        self._engine = engine
        self._conversation_id = conversation_id

    def step(self, state: TaskState, kind: str, **fields: Any) -> None:
        engine = self._engine
        n = engine._step_n.get(state.task_id)
        if n is None:
            row = engine._conn.execute(
                "SELECT COALESCE(MAX(n), 0) FROM task_steps WHERE task_id = ?", (state.task_id,)
            ).fetchone()
            n = row[0]
        n += 1
        engine._step_n[state.task_id] = n
        engine._conn.execute(
            "INSERT INTO task_steps (id, task_id, n, kind, model, tool, args, result, decision, tokens, duration_ms,"
            " created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                uuid7(),
                state.task_id,
                n,
                kind,
                fields.get("model"),
                fields.get("tool"),
                fields.get("args", "{}"),
                fields.get("result"),
                fields.get("decision"),
                fields.get("tokens", 0),
                fields.get("duration_ms", 0),
                utcnow(),
            ),
        )
        self.emit(
            state, "agent.step", {"kind": kind, "tool": fields.get("tool"), "n": n, "decision": fields.get("decision")}
        )

    def update(self, state: TaskState, **fields: Any) -> None:
        sets = ["steps_used = ?", "tokens_in = ?", "tokens_out = ?", "cost_usd = ?", "tainted = ?"]
        params: list[Any] = [state.steps_used, state.tokens_in, state.tokens_out, state.cost_usd, int(state.tainted)]
        for key in ("status", "model"):
            if key in fields:
                sets.append(f"{key} = ?")
                params.append(fields[key])
        self._engine._conn.execute(
            f"UPDATE agent_tasks SET {', '.join(sets)} WHERE id = ?",  # noqa: S608
            (*params, state.task_id),
        )

    async def ask(
        self, state: TaskState, agent: AgentDefinition, tool: Tool, args: BaseModel, decision: Decision
    ) -> bool:
        return await self._engine.ask(state, agent, tool, args, decision)

    def emit(self, state: TaskState, event_type: str, payload: dict[str, Any]) -> None:
        self._engine._bus.publish(
            event_type,
            {"task_id": state.task_id, "agent_id": state.agent_id, **payload},
            actor=f"agent:{state.agent_id}",
            subject_type="task",
            subject_id=state.task_id,
        )

    def audit(self, state: TaskState, action: str, details: dict[str, Any], outcome: str = "ok") -> None:
        self._engine._audit.append(
            actor=f"agent:{state.agent_id}",
            action=action,
            target_type="task",
            target_id=state.task_id,
            details=details,
            outcome=outcome,
            task_id=state.task_id,
        )

    def usage(self, state: TaskState, model: str, tokens_in: int, tokens_out: int) -> None:
        self._engine._conn.execute(
            "INSERT INTO usage_ledger (id, ts, task_id, agent_id, provider, model, tokens_in, tokens_out, cost_usd)"
            " VALUES (?, ?, ?, ?, 'ollama', ?, ?, ?, 0)",
            (uuid7(), utcnow(), state.task_id, state.agent_id, model, tokens_in, tokens_out),
        )

    def context(self, agent: AgentDefinition, text: str) -> str:
        return self._engine.memory.context_block(text, scopes_for(agent.id, agent.memory))
