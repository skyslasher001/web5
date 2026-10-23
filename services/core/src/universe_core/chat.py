"""Chat with an agent: store messages, stream the reply as events, record timings.

Each turn is one agent task: agent.started → chat.started → chat.token… → chat.message → agent.completed.
"""

import asyncio
import sqlite3
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from universe_agents.providers import ChatMessage, ChatProvider, ProviderError
from universe_agents.registry import AgentDefinition
from universe_agents.router import ModelRouter, NoModelAvailable
from universe_common.errors import capture_exception
from universe_common.ids import is_uuid, uuid7
from universe_common.log import get_logger
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_core.errors import ErrorStore
from universe_core.events import EventBus

if TYPE_CHECKING:
    from universe_core.agent_engine import AgentEngine

log = get_logger(__name__)

MAX_INPUT_CHARS = 20_000
HISTORY_MESSAGES = 30
HISTORY_CHARS = 24_000


class ChatError(ValueError):
    """Bad request (user-presentable)."""


class ChatUnavailable(RuntimeError):
    """Chat can't run right now (safe mode). User-presentable."""


class Conversation(ApiModel):
    id: str
    title: str
    agent_id: str
    created_at: str
    updated_at: str


class Message(ApiModel):
    id: str
    conversation_id: str
    role: Literal["user", "assistant", "system"]
    agent_id: str | None
    content: str
    model: str | None
    status: Literal["complete", "cancelled", "failed"]
    first_token_ms: int | None
    total_ms: int | None
    task_id: str | None  # the agent task behind a reply through the engine: its trace
    created_at: str


@dataclass(frozen=True)
class SendResult:
    conversation_id: str
    user_message_id: str
    assistant_message_id: str


def _message(row: sqlite3.Row) -> Message:
    return Message(**{k: row[k] for k in Message.model_fields})


class ChatService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        bus: EventBus,
        agents: dict[str, AgentDefinition],
        router: ModelRouter,
        provider: ChatProvider,
        errors: ErrorStore,
        *,
        safe_mode: bool,
    ) -> None:
        self._conn = conn
        self._bus = bus
        self._agents = agents
        self._router = router
        self._provider = provider
        self._errors = errors
        self._safe_mode = safe_mode
        self._active: dict[str, asyncio.Task[None]] = {}
        self.engine: AgentEngine | None = None  # set by CoreContext; with it, each reply is an agent task

    @property
    def active_conversations(self) -> list[str]:
        return list(self._active)

    def is_agent_busy(self, agent_id: str) -> bool:
        return any(task.get_name() == f"chat:{agent_id}" for task in self._active.values())

    def conversations(self, limit: int = 50) -> list[Conversation]:
        rows = self._conn.execute("SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (min(limit, 500),))
        return [Conversation(**{k: r[k] for k in Conversation.model_fields}) for r in rows]

    def messages(self, conversation_id: str, limit: int = 500) -> list[Message]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at, rowid LIMIT ?",
            (conversation_id, min(limit, 5000)),
        )
        return [_message(r) for r in rows]

    async def send(self, *, text: str, conversation_id: str | None = None, agent_id: str = "core") -> SendResult:
        text = text.strip()
        if not text:
            raise ChatError("Message is empty")
        if len(text) > MAX_INPUT_CHARS:
            raise ChatError(f"Message is longer than {MAX_INPUT_CHARS} characters")
        if self._safe_mode:
            raise ChatUnavailable("Agents are disabled in safe mode")
        agent = self._agents.get(agent_id)
        if agent is None:
            raise ChatError(f"Unknown agent '{agent_id}'")
        now = utcnow()
        exists = conversation_id is not None and bool(
            self._conn.execute("SELECT 1 FROM conversations WHERE id = ?", (conversation_id,)).fetchone()
        )
        if not exists:
            # Clients may name a new conversation (a UUID) so they can match its events immediately.
            if conversation_id is not None and not is_uuid(conversation_id):
                raise ChatError("Unknown conversation")
            conversation_id = conversation_id or uuid7()
            title = text.splitlines()[0][:60]
            self._conn.execute(
                "INSERT INTO conversations (id, title, agent_id, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (conversation_id, title, agent.id, now, now),
            )
        else:
            assert conversation_id is not None
            if conversation_id in self._active:
                raise ChatError("A reply is already streaming in this conversation")
            self._conn.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, conversation_id))
        user_message = self._insert_message(conversation_id, "user", None, text, None, "complete", None, None)
        self._publish_message(user_message)
        assistant_id = uuid7()
        reply = (
            self._agent_reply(conversation_id, agent, assistant_id, text)
            if self.engine is not None and self.engine.available
            else self._reply(conversation_id, agent, assistant_id)
        )
        task = asyncio.create_task(reply, name=f"chat:{agent.id}")
        self._active[conversation_id] = task
        task.add_done_callback(lambda _t, cid=conversation_id: self._active.pop(cid, None))
        return SendResult(conversation_id, user_message.id, assistant_id)

    def cancel(self, conversation_id: str) -> bool:
        task = self._active.get(conversation_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def shutdown(self) -> None:
        tasks = list(self._active.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    def _insert_message(
        self,
        conversation_id: str,
        role: str,
        agent_id: str | None,
        content: str,
        model: str | None,
        status: str,
        first_token_ms: int | None,
        total_ms: int | None,
        message_id: str | None = None,
        task_id: str | None = None,
    ) -> Message:
        row = self._conn.execute(
            "INSERT INTO messages (id, conversation_id, role, agent_id, content, model, status, first_token_ms,"
            " total_ms, task_id, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) RETURNING *",
            (
                message_id or uuid7(),
                conversation_id,
                role,
                agent_id,
                content,
                model,
                status,
                first_token_ms,
                total_ms,
                task_id,
                utcnow(),
            ),
        ).fetchone()
        return _message(row)

    def _publish_message(self, message: Message) -> None:
        self._bus.publish(
            "chat.message",
            message.model_dump(),
            actor="user" if message.role == "user" else f"agent:{message.agent_id}",
            subject_type="conversation",
            subject_id=message.conversation_id,
        )

    def _history(self, conversation_id: str, agent: AgentDefinition) -> list[ChatMessage]:
        rows = self._conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? AND content != ''"
            " ORDER BY created_at DESC, rowid DESC LIMIT ?",
            (conversation_id, HISTORY_MESSAGES),
        ).fetchall()
        history: list[ChatMessage] = []
        budget = HISTORY_CHARS
        for row in rows:  # newest first; stop when the budget runs out
            budget -= len(row["content"])
            if budget < 0 and history:
                break
            history.append({"role": row["role"], "content": row["content"]})
        history.reverse()
        return [{"role": "system", "content": agent.system_prompt}, *history]

    async def _agent_reply(self, conversation_id: str, agent: AgentDefinition, message_id: str, text: str) -> None:
        """A reply through the agent engine: tools, approvals, delegation and Critic, streamed as chat tokens.

        Same events and stored message as a plain reply (Phase 1), plus the task and its trace.
        """
        assert self.engine is not None
        actor = f"agent:{agent.id}"
        subject = {"subject_type": "conversation", "subject_id": conversation_id, "correlation_id": message_id}
        base = {"conversation_id": conversation_id, "message_id": message_id}
        try:
            model = await self._router.resolve(agent.model, needs_tools=bool(agent.tools))
        except NoModelAvailable:
            # No installed model can call tools: answer without them rather than not at all.
            await self._reply(conversation_id, agent, message_id)
            return
        started = time.monotonic()
        parts: list[str] = []
        first: list[int] = []

        def on_started() -> None:
            self._bus.publish("chat.started", {**base, "model": model, "agent_id": agent.id}, actor=actor, **subject)

        def on_token(delta: str) -> None:
            if not first:
                first.append(int((time.monotonic() - started) * 1000))
            parts.append(delta)
            self._bus.publish("chat.token", {**base, "delta": delta}, actor=actor, **subject)

        history = self._history(conversation_id, agent)[1:]  # without the system prompt; the agent adds its own
        if history and history[-1]["role"] == "user":
            history.pop()  # the message being answered is the task's instruction
        task = None
        try:
            task, _outcome = await self.engine.run(
                agent.id,
                text,
                conversation_id=conversation_id,
                history=[dict(m) for m in history],
                on_token=on_token,
                on_started=on_started,
                correlation_id=message_id,
            )
        except asyncio.CancelledError:
            total_ms = int((time.monotonic() - started) * 1000)
            first_ms = first[0] if first else None
            if parts:  # keep what was said before you stopped it
                message = self._insert_message(
                    conversation_id,
                    "assistant",
                    agent.id,
                    "".join(parts),
                    model,
                    "cancelled",
                    first_ms,
                    total_ms,
                    message_id,
                )
                self._publish_message(message)
            self._bus.publish(
                "chat.cancelled",
                {**base, "first_token_ms": first_ms, "total_ms": total_ms, "model": model},
                actor=actor,
                **subject,
            )
            raise
        total_ms = int((time.monotonic() - started) * 1000)
        timing = {"first_token_ms": first[0] if first else None, "total_ms": total_ms, "model": model}
        if task.status == "done":
            message = self._insert_message(
                conversation_id,
                "assistant",
                agent.id,
                task.output or "",
                task.model,
                "complete",
                timing["first_token_ms"],
                total_ms,
                message_id,
                task.id,
            )
            self._publish_message(message)
            self._bus.publish("chat.completed", {**base, **timing, "task_id": task.id}, actor=actor, **subject)
            return
        if task.status == "cancelled":
            self._bus.publish("chat.cancelled", {**base, **timing}, actor=actor, **subject)
            return
        code = self.engine.failure_codes.pop(task.id, "agent")
        hint = {"provider": "Check that Ollama is running.", "policy": "", "step_limit": ""}.get(code, "")
        self._bus.publish(
            "chat.failed",
            {**base, "code": code, "error": task.error or "The task failed", "hint": hint, "task_id": task.id},
            actor=actor,
            **subject,
        )

    async def _reply(self, conversation_id: str, agent: AgentDefinition, message_id: str) -> None:
        actor = f"agent:{agent.id}"
        subject = {
            "subject_type": "conversation",
            "subject_id": conversation_id,
            "correlation_id": message_id,
        }
        self._bus.publish(
            "agent.started",
            {"agent_id": agent.id, "conversation_id": conversation_id},
            actor=actor,
            **subject,
        )
        started = time.monotonic()
        parts: list[str] = []
        first_token_ms: int | None = None
        model: str | None = None
        status = "failed"
        failure: dict[str, str] | None = None
        cancelled = False
        try:
            model = await self._router.resolve(agent.model)
            self._bus.publish(
                "chat.started",
                {
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "model": model,
                    "agent_id": agent.id,
                },
                actor=actor,
                **subject,
            )
            async with asyncio.timeout(agent.limits.timeout_s):
                stream = self._provider.stream(
                    model,
                    self._history(conversation_id, agent),
                    max_tokens=agent.limits.max_tokens,
                    temperature=0.7,
                )
                async for delta in stream:
                    if first_token_ms is None:
                        first_token_ms = int((time.monotonic() - started) * 1000)
                    parts.append(delta)
                    self._bus.publish(
                        "chat.token",
                        {"conversation_id": conversation_id, "message_id": message_id, "delta": delta},
                        actor=actor,
                        **subject,
                    )
            status = "complete"
        except asyncio.CancelledError:
            status = "cancelled"
            cancelled = True
        except NoModelAvailable as exc:
            failure = {"code": "no_model", "error": str(exc), "hint": exc.hint}
        except ProviderError as exc:
            failure = {"code": "provider", "error": str(exc), "hint": "Check that Ollama is running."}
        except TimeoutError:
            failure = {
                "code": "timeout",
                "error": f"No complete reply within {agent.limits.timeout_s} s",
                "hint": "",
            }
        except Exception as exc:
            captured = capture_exception(exc, {"conversation_id": conversation_id, "agent": agent.id})
            self._errors.record(
                service="core",
                kind=captured.kind,
                message=captured.message,
                stack=captured.stack,
                fingerprint=captured.fingerprint,
                context=captured.context,
            )
            log.exception("chat_reply_failed", conversation_id=conversation_id)
            failure = {
                "code": "internal",
                "error": "Something went wrong; the error was recorded.",
                "hint": "",
            }
        total_ms = int((time.monotonic() - started) * 1000)
        content = "".join(parts)
        if content or status == "complete":
            message = self._insert_message(
                conversation_id,
                "assistant",
                agent.id,
                content,
                model,
                status,
                first_token_ms,
                total_ms,
                message_id,
            )
            self._publish_message(message)
        timing = {"first_token_ms": first_token_ms, "total_ms": total_ms, "model": model}
        base = {"conversation_id": conversation_id, "message_id": message_id}
        if status == "complete":
            self._bus.publish("chat.completed", {**base, **timing}, actor=actor, **subject)
            self._bus.publish("agent.completed", {"agent_id": agent.id, **base, **timing}, actor=actor, **subject)
        elif cancelled:
            self._bus.publish("chat.cancelled", {**base, **timing}, actor=actor, **subject)
            self._bus.publish(
                "agent.completed",
                {"agent_id": agent.id, **base, **timing, "cancelled": True},
                actor=actor,
                **subject,
            )
        else:
            self._bus.publish("chat.failed", {**base, **(failure or {})}, actor=actor, **subject)
            self._bus.publish("agent.failed", {"agent_id": agent.id, **base, **(failure or {})}, actor=actor, **subject)
        if cancelled:
            raise asyncio.CancelledError
