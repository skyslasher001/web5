"""Event bus: in-process pub/sub, persisted to events.db for the event types marked P (ARCHITECTURE.md §5.3).

`publish` must be called from the event-loop thread (subscriber queues are asyncio queues).
"""

import asyncio
import json
import sqlite3
from dataclasses import dataclass
from fnmatch import fnmatchcase
from typing import Any

from pydantic import Field

from universe_common.ids import uuid7
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow


@dataclass(frozen=True)
class EventType:
    persisted: bool
    description: str


def _p(description: str) -> EventType:
    return EventType(True, description)


def _live(description: str) -> EventType:
    return EventType(False, description)


CATALOG: dict[str, EventType] = {
    # Items (Phase 2)
    "item.created": _p("An item entered the vault"),
    "item.updated": _p("Item metadata or content changed"),
    "item.deleted": _p("Item purged everywhere"),
    "item.opened": _p("You opened an item"),
    "item.processed": _p("Pipeline finished for an item"),
    "item.trashed": _p("Item moved to trash"),
    "item.restored": _p("Item restored from trash"),
    # Pipeline / jobs (Phase 2)
    "pipeline.stage.started": _live("A pipeline stage started"),
    "pipeline.stage.completed": _p("A pipeline stage completed"),
    "pipeline.stage.failed": _p("A pipeline stage failed"),
    "job.queued": _live("Job queued"),
    "job.progress": _live("Job progress"),
    "job.completed": _live("Job completed"),
    "job.failed": _p("Job failed (will retry)"),
    "job.dead": _p("Job gave up after retries"),
    # Graph
    "link.suggested": _p("An agent suggested a link"),
    "link.confirmed": _p("You confirmed a link"),
    "link.rejected": _p("You rejected a link"),
    "tag.suggested": _live("An agent suggested a tag"),
    "tag.confirmed": _p("A tag was confirmed"),
    "project.created": _p("A project (galaxy) was created"),
    "project.updated": _p("A project changed"),
    "idea.stage_changed": _p("An idea matured"),
    "idea.promoted": _p("An idea became a project"),
    # Search / navigation
    "recall.performed": _p("A recall query ran"),
    # Research (Phase 6)
    "research.watchlist.changed": _p("A watched topic or page changed"),
    "view.changed": _live("Layout or zoom changed"),
    "layout.updated": _p("A cached universe layout was recomputed"),
    "link.created": _p("Two items were linked"),
    "link.deleted": _p("A link was removed"),
    "link.fired": _live("Two items fired together: you or an agent moved from one to the other (a signal pulse)"),
    "navigator.action": _live("Navigator executed a command"),
    # Chat
    "chat.message": _p("A chat message was stored"),
    "chat.started": _live("A reply started streaming"),
    "chat.token": _live("Streamed reply tokens"),
    "chat.completed": _live("A reply finished streaming"),
    "chat.cancelled": _live("A reply was cancelled"),
    "chat.failed": _p("A reply failed"),
    # Agents
    "agent.started": _p("An agent started a task"),
    "agent.step": _live("An agent took a step"),
    "agent.tool_call": _p("An agent called a tool"),
    "agent.message": _p("Agent-to-agent message"),
    "agent.completed": _p("An agent finished a task"),
    "agent.failed": _p("An agent task failed"),
    "agent.reloaded": _p("Agent definition reloaded"),
    "agent.added": _p("The owner added an agent"),
    "agent.updated": _p("An agent was turned on or off, or its synopsis changed"),
    "agent.removed": _p("The owner removed one of their agents"),
    # Approvals (Phase 3)
    "approval.requested": _p("Approval requested"),
    "approval.decided": _p("Approval decided"),
    "approval.expired": _p("Approval expired"),
    # Memory (Phase 3/9)
    "memory.created": _p("Memory created"),
    "memory.proposed": _p("Memory proposed for approval"),
    "memory.updated": _p("Memory updated"),
    "memory.deleted": _p("Memory deleted"),
    "consolidation.completed": _p("Nightly consolidation finished"),
    "contradiction.detected": _p("Contradicting memories found"),
    # Consent & safety
    "consent.changed": _p("Mic, screen or camera consent changed"),
    "killswitch.engaged": _p("Kill switch engaged"),
    "killswitch.released": _p("Kill switch released"),
    "offline.changed": _p("Offline switch changed"),
    "capture.started": _p("Capture started"),
    "capture.stopped": _p("Capture stopped"),
    "capture.saved": _p("Capture saved to the vault"),
    # Budget (Phase 3)
    "budget.usage": _live("Budget usage update"),
    "budget.warning": _p("Budget warning threshold crossed"),
    "budget.cap_reached": _p("Budget cap reached"),
    # Voice (Phase 7)
    "voice.state": _live("Voice orb state"),
    "voice.level": _live("Mic level"),
    "voice.transcript.partial": _live("Partial transcript"),
    "voice.transcript.final": _p("Final transcript"),
    "voice.tts.started": _live("Speech started"),
    "voice.tts.stopped": _live("Speech stopped"),
    "voice.barge_in": _live("You interrupted speech"),
    "voice.service.changed": _p("The voice process started, stopped or failed"),
    "voice.settings.changed": _p("Voice settings changed"),
    "voice.model.progress": _live("Voice model download progress"),
    "voice.model.installed": _p("A voice model was installed"),
    "voice.model.failed": _p("A voice model failed to install"),
    # Errors & health
    "error.raised": _p("An error was captured"),
    "service.started": _p("A service started"),
    "service.crashed": _p("A service crashed"),
    "service.restarted": _p("A service was restarted"),
    "safe_mode.entered": _p("Safe mode entered"),
    "governor.paused": _p("Background work paused"),
    "governor.resumed": _p("Background work resumed"),
    # Forge / Sentinel (Phase 5)
    "forge.issue.triaged": _p("Forge triaged an issue"),
    "forge.proposal.created": _p("Forge proposed a change"),
    "forge.proposal.verified": _p("A proposal passed verification"),
    "forge.applied": _p("A change was applied"),
    "forge.rolled_back": _p("A change was rolled back"),
    "sentinel.alert": _p("Sentinel raised an alert"),
    "backup.completed": _p("Backup completed"),
    "backup.failed": _p("A backup, restore or restore test failed"),
    "backup.restored": _p("A backup was restored to a folder"),
    "backup.restore_tested": _p("Backup restore test ran"),
    # Models
    "model.pull.progress": _live("Model download progress"),
    "model.loaded": _live("Model loaded"),
    "model.unloaded": _live("Model unloaded"),
    "model.assignment_changed": _p("Model assignment changed"),
}


class UnknownEventType(ValueError):
    pass


class Event(ApiModel):
    id: str
    seq: int | None = None
    ts: str
    type: str
    source: str
    actor: str
    subject_type: str | None = None
    subject_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    v: int = 1


class Subscription:
    def __init__(self, patterns: list[str], maxsize: int = 2000) -> None:
        self.patterns = list(patterns)
        self.queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=maxsize)
        self.overflowed = False

    def matches(self, event_type: str) -> bool:
        return any(fnmatchcase(event_type, p) for p in self.patterns)


class EventBus:
    def __init__(self, conn: sqlite3.Connection, *, source: str = "core") -> None:
        self._conn = conn
        self._source = source
        self._subs: set[Subscription] = set()

    def subscribe(self, patterns: list[str]) -> Subscription:
        sub = Subscription(patterns)
        self._subs.add(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> None:
        self._subs.discard(sub)

    @property
    def subscriber_count(self) -> int:
        return len(self._subs)

    def publish(
        self,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "system",
        subject_type: str | None = None,
        subject_id: str | None = None,
        correlation_id: str | None = None,
        causation_id: str | None = None,
        source: str | None = None,
    ) -> Event:
        spec = CATALOG.get(event_type)
        if spec is None:
            raise UnknownEventType(event_type)
        event = Event(
            id=uuid7(),
            ts=utcnow(),
            type=event_type,
            source=source or self._source,
            actor=actor,
            subject_type=subject_type,
            subject_id=subject_id,
            correlation_id=correlation_id,
            causation_id=causation_id,
            payload=payload or {},
        )
        if spec.persisted:
            cursor = self._conn.execute(
                "INSERT INTO events (id, ts, type, source, actor, subject_type, subject_id, correlation_id,"
                " causation_id, payload, v) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    event.id,
                    event.ts,
                    event.type,
                    event.source,
                    event.actor,
                    event.subject_type,
                    event.subject_id,
                    event.correlation_id,
                    event.causation_id,
                    json.dumps(event.payload, ensure_ascii=False),
                    event.v,
                ),
            )
            event.seq = cursor.lastrowid
        for sub in list(self._subs):
            if sub.overflowed or not sub.matches(event_type):
                continue
            try:
                sub.queue.put_nowait(event)
            except asyncio.QueueFull:
                sub.overflowed = True  # the WebSocket closes and the client resumes with since_seq
        return event

    def replay(self, since_seq: int = 0, *, limit: int = 500, types: list[str] | None = None) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM events WHERE seq > ? ORDER BY seq LIMIT ?", (since_seq, min(limit, 5000))
        ).fetchall()
        events = [
            Event(**{**dict(row), "payload": json.loads(row["payload"])})
            for row in rows
            if not types or any(fnmatchcase(row["type"], t) for t in types)
        ]
        return events

    def tail(self, count: int) -> list[Event]:
        rows = self._conn.execute(
            "SELECT * FROM (SELECT * FROM events ORDER BY seq DESC LIMIT ?) ORDER BY seq", (min(count, 5000),)
        ).fetchall()
        return [Event(**{**dict(row), "payload": json.loads(row["payload"])}) for row in rows]

    def last_seq(self) -> int:
        row = self._conn.execute("SELECT MAX(seq) AS seq FROM events").fetchone()
        return int(row["seq"] or 0)
