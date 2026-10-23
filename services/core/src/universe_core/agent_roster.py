"""The agent roster behind the Agents tab: the built-in agents (agents/*.yaml, shipped with the app and never
edited by it), the owner's own agents (<data dir>/agents/, so updates never clash with them), which agents are
turned off, synopsis edits, and per-agent stats.

The live `agents` dict that the engine and chat use is updated in place, so a change takes effect on the next
task. Core runs every task and Critic reviews every task that changes something, so neither can be turned off;
Forge and Sentinel are protected core.
"""

import json
import re
import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import yaml

from universe_agents.registry import AgentConfigError, AgentDefinition, load_agent
from universe_common.log import get_logger
from universe_common.sqlite import transaction
from universe_common.timeutil import utcnow

log = get_logger(__name__)

REQUIRED = {
    "core": "Core runs every task, so it can't be turned off.",
    "critic": "Critic reviews every task that changes something, so it can't be turned off.",
    "forge": "Forge is protected core.",
    "sentinel": "Sentinel is protected core.",
}
DISABLED_KEY = "agents.disabled"
SYNOPSIS_KEY = "agent.synopsis.{}"
# Your own agents can read and write through the same permission rules and approvals as the built-in ones;
# system-tier tools and delegation stay with the built-in agents.
CUSTOM_TIERS = ("read", "write")
CUSTOM_MODELS = ("local-fast", "local-large")
NOT_FOR_CUSTOM = {"agent.delegate"}


@dataclass(frozen=True)
class AgentStats:
    tasks: int = 0
    done: int = 0
    failed: int = 0
    cancelled: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    avg_steps: float | None = None
    last_active: str | None = None

    @property
    def success_rate(self) -> float | None:
        finished = self.done + self.failed
        return round(self.done / finished, 3) if finished else None


@dataclass(frozen=True)
class RosterEntry:
    agent: AgentDefinition
    origin: str  # "built-in" | "custom"
    enabled: bool
    locked_reason: str | None  # why it can't be turned off or removed


def slug_id(name: str) -> str:
    """An agent id from its name: lowercase letters, digits and '-', starting with a letter, 2–32 chars."""
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slug = re.sub(r"^[^a-z]+", "", slug)[:32].strip("-")
    return slug if len(slug) >= 2 else f"agent-{slug}".strip("-")[:32]


class AgentRoster:
    def __init__(
        self,
        db: sqlite3.Connection,
        builtin: dict[str, AgentDefinition],
        custom_dir: Path,
        live: dict[str, AgentDefinition],
    ) -> None:
        self._db = db
        self._custom_dir = custom_dir
        self._live = live
        self._all: dict[str, AgentDefinition] = dict(builtin)
        self._origin = dict.fromkeys(builtin, "built-in")
        for path in sorted(custom_dir.glob("*.yaml")) if custom_dir.is_dir() else []:
            try:
                agent = load_agent(path)
            except AgentConfigError as exc:  # one broken file never stops Core
                log.warning("custom_agent_invalid", error=str(exc))
                continue
            if agent.id in self._all:
                log.warning("custom_agent_shadows_builtin", agent=agent.id)
                continue
            self._all[agent.id] = agent
            self._origin[agent.id] = "custom"
        for agent_id, agent in self._all.items():
            override = self._setting(SYNOPSIS_KEY.format(agent_id))
            if override is not None:
                agent.synopsis = override
        self._sync_live()

    # ---------- reading ----------

    def entries(self) -> list[RosterEntry]:
        disabled = self._disabled()
        order = sorted(self._all, key=lambda a: (self._origin[a] != "built-in", a != "core", a))
        return [RosterEntry(self._all[a], self._origin[a], a not in disabled, REQUIRED.get(a)) for a in order]

    def entry(self, agent_id: str) -> RosterEntry:
        for e in self.entries():
            if e.agent.id == agent_id:
                return e
        raise LookupError(f"No agent called '{agent_id}'")

    def stats(self) -> dict[str, AgentStats]:
        rows = self._db.execute(
            "SELECT agent_id, COUNT(*) AS tasks, SUM(status = 'done') AS done, SUM(status = 'failed') AS failed,"
            " SUM(status = 'cancelled') AS cancelled, SUM(tokens_in) AS tin, SUM(tokens_out) AS tout,"
            " SUM(cost_usd) AS cost, AVG(CASE WHEN status = 'done' THEN steps_used END) AS steps,"
            " MAX(created_at) AS last FROM agent_tasks GROUP BY agent_id"
        ).fetchall()
        return {
            r["agent_id"]: AgentStats(
                tasks=r["tasks"],
                done=r["done"] or 0,
                failed=r["failed"] or 0,
                cancelled=r["cancelled"] or 0,
                tokens_in=r["tin"] or 0,
                tokens_out=r["tout"] or 0,
                cost_usd=round(float(r["cost"] or 0), 4),
                avg_steps=round(float(r["steps"]), 1) if r["steps"] is not None else None,
                last_active=r["last"],
            )
            for r in rows
        }

    # ---------- changing ----------

    def create(
        self,
        *,
        name: str,
        purpose: str,
        synopsis: str,
        instructions: str,
        color: str,
        tools: list[str],
        permission_tier: str,
        model: str,
        max_steps: int,
        known_tools: set[str],
    ) -> AgentDefinition:
        agent_id = slug_id(name)
        if agent_id in self._all or agent_id in REQUIRED:
            raise ValueError(f"There's already an agent called '{agent_id}'. Pick another name.")
        if permission_tier not in CUSTOM_TIERS:
            raise ValueError("Your own agents can have read or write access.")
        if model not in CUSTOM_MODELS:
            raise ValueError(f"Model must be one of {', '.join(CUSTOM_MODELS)}.")
        unknown = sorted(t for t in tools if t not in known_tools or t in NOT_FOR_CUSTOM)
        if unknown:
            raise ValueError(f"Unknown or unavailable tools: {', '.join(unknown)}")
        self._custom_dir.mkdir(parents=True, exist_ok=True)
        (self._custom_dir / "prompts").mkdir(exist_ok=True)
        prompt = self._custom_dir / "prompts" / f"{agent_id}.md"
        path = self._custom_dir / f"{agent_id}.yaml"
        definition = {
            "id": agent_id,
            "name": name.strip(),
            "purpose": purpose.strip(),
            "synopsis": synopsis.strip(),
            "model": model,
            "color": color,
            "tools": sorted(set(tools)),
            "permission_tier": permission_tier,
            "memory": ["shared"],
            "triggers": [{"manual": True}],
            "limits": {"max_steps": max_steps, "max_tokens": 6144, "timeout_s": 300},
            "requires_approval": [],
            "prompt": f"prompts/{agent_id}.md",
        }
        prompt.write_text(instructions.strip() + "\n", encoding="utf-8")
        path.write_text(yaml.safe_dump(definition, sort_keys=False, allow_unicode=True), encoding="utf-8")
        try:
            agent = load_agent(path)  # the same validation as the built-in agents
        except AgentConfigError:
            path.unlink(missing_ok=True)
            prompt.unlink(missing_ok=True)
            raise
        self._all[agent.id] = agent
        self._origin[agent.id] = "custom"
        self._sync_live()
        return agent

    def set_enabled(self, agent_id: str, enabled: bool) -> None:
        self.entry(agent_id)  # exists
        if not enabled and agent_id in REQUIRED:
            raise ValueError(REQUIRED[agent_id])
        disabled = self._disabled()
        disabled = disabled - {agent_id} if enabled else disabled | {agent_id}
        self._put(DISABLED_KEY, json.dumps(sorted(disabled)))
        self._sync_live()

    def set_synopsis(self, agent_id: str, synopsis: str) -> None:
        agent = self.entry(agent_id).agent
        text = synopsis.strip()
        if self._origin[agent_id] == "custom":
            path = self._custom_dir / f"{agent_id}.yaml"
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            raw["synopsis"] = text
            path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
        else:  # the shipped YAML stays as it is; your edit lives in settings
            self._put(SYNOPSIS_KEY.format(agent_id), text)
        agent.synopsis = text

    def remove(self, agent_id: str) -> Path:
        """Remove one of your own agents. Its files move to <data dir>/agents/.removed/ (nothing is deleted)."""
        entry = self.entry(agent_id)
        if entry.origin != "custom":
            raise ValueError("Built-in agents can be turned off, not removed.")
        dest = self._custom_dir / ".removed" / f"{agent_id}-{utcnow().replace(':', '').replace('.', '')}"
        dest.mkdir(parents=True)
        for src in (self._custom_dir / f"{agent_id}.yaml", self._custom_dir / "prompts" / f"{agent_id}.md"):
            if src.exists():
                shutil.move(str(src), str(dest / src.name))
        del self._all[agent_id]
        del self._origin[agent_id]
        self._put(DISABLED_KEY, json.dumps(sorted(self._disabled() - {agent_id})))
        self._sync_live()
        return dest

    # ---------- helpers ----------

    def _sync_live(self) -> None:
        disabled = self._disabled()
        wanted = {a: d for a, d in self._all.items() if a not in disabled or a in REQUIRED}
        for agent_id in list(self._live):
            if agent_id not in wanted:
                del self._live[agent_id]
        self._live.update(wanted)

    def _disabled(self) -> set[str]:
        raw = self._setting(DISABLED_KEY)
        try:
            value = json.loads(raw) if raw else []
        except json.JSONDecodeError:
            value = []
        return {str(v) for v in value if isinstance(v, str)}

    def _setting(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else None

    def _put(self, key: str, value: str) -> None:
        with transaction(self._db):
            self._db.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
                " ON CONFLICT (key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
                (key, value, utcnow()),
            )
