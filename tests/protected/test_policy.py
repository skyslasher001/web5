"""The policy engine decides every agent call (ARCHITECTURE.md §7.3). PROTECTED: Forge may not change these."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from universe_agents.registry import AgentDefinition, AgentLimits
from universe_agents.runtime import TaskState
from universe_agents.tools import Tool, ToolContext, ToolResult
from universe_common.ids import uuid7
from universe_common.sqlite import connect, migrate_up
from universe_common.timeutil import utcnow
from universe_core.db import migrations_dir
from universe_core.protected.budget import Budget, BudgetCaps
from universe_core.protected.killswitch import KillSwitch
from universe_core.protected.permissions import PermissionStore, RuleRequest
from universe_core.protected.policy import PolicyEngine


class NoArgs(BaseModel):
    pass


async def _noop(_args: BaseModel, _ctx: ToolContext) -> ToolResult:
    return ToolResult("ok")


def tool(name: str, tier: str = "read", **flags: Any) -> Tool:
    return Tool(name, "", NoArgs, tier, _noop, **flags)  # type: ignore[arg-type]


def agent(tier: str = "write", requires_approval: list[str] | None = None, **limits: int) -> AgentDefinition:
    return AgentDefinition(
        id="scribe",
        name="Scribe",
        purpose="",
        model="local-fast",
        color="green",
        permission_tier=tier,  # type: ignore[arg-type]
        limits=AgentLimits(**{"max_steps": 5, "max_tokens": 1000, "timeout_s": 60, **limits}),
        requires_approval=requires_approval or [],
        prompt="p.md",
    )


class Rig:
    def __init__(self, tmp_path: Path) -> None:
        self.conn = connect(tmp_path / "universe.db")
        migrate_up(self.conn, migrations_dir("universe"))
        self.audited: list[dict[str, Any]] = []
        self.events: list[tuple[str, dict[str, Any]]] = []
        self.halted: list[bool] = []
        self.killswitch = KillSwitch(
            tmp_path / "data", audit=self._audit, publish=self._publish, on_change=self.halted.append
        )
        self.permissions = PermissionStore(self.conn, self._audit)
        self.budget = Budget(self.conn, self._audit, self._publish)
        self.policy = PolicyEngine(killswitch=self.killswitch, permissions=self.permissions, budget=self.budget)

    def _audit(self, **entry: Any) -> None:
        self.audited.append(entry)

    def _publish(self, event: str, payload: dict[str, Any]) -> None:
        self.events.append((event, payload))

    def check(self, t: Tool, a: AgentDefinition | None = None, *, tainted: bool = False) -> str:
        state = TaskState(task_id="t", agent_id="scribe", tainted=tainted)
        return self.policy.check_tool(a or agent(), t, NoArgs(), state).verdict

    def spend(self, usd: float) -> None:
        self.conn.execute(
            "INSERT INTO usage_ledger (id, ts, provider, model, cost_usd) VALUES (?, ?, 'cloud', 'm', ?)",
            (uuid7(), utcnow(), usd),
        )


@pytest.fixture
def rig(tmp_path: Path) -> Rig:
    return Rig(tmp_path)


def test_defaults_by_tier(rig: Rig) -> None:
    assert rig.check(tool("vault.search")) == "allow"
    assert rig.check(tool("project.add_items", "write", side_effects=True)) == "allow"
    assert rig.check(tool("note.create", "write"), agent(requires_approval=["note.*"])) == "ask"
    assert rig.check(tool("shell.run", "system"), agent("system")) == "ask"  # system always asks
    assert rig.check(tool("mcp.fs.write", "write", ask_first=True)) == "ask"


def test_an_agent_never_exceeds_its_tier(rig: Rig) -> None:
    assert rig.check(tool("note.create", "write"), agent("read")) == "deny"
    assert rig.check(tool("shell.run", "system"), agent("write")) == "deny"
    # Not even with a rule that allows it.
    rig.permissions.add(RuleRequest(agent_id="scribe", tool="shell.run", decision="allow"))
    assert rig.check(tool("shell.run", "system"), agent("write")) == "deny"


def test_taint_makes_side_effects_and_network_ask(rig: Rig) -> None:
    assert rig.check(tool("vault.read"), tainted=True) == "allow"  # reading more is fine
    assert rig.check(tool("project.add_items", "write", side_effects=True), tainted=True) == "ask"
    assert rig.check(tool("web.fetch", "read", network=True), tainted=True) == "ask"


def test_rules_most_specific_first_and_strictest_on_ties(rig: Rig) -> None:
    t = tool("project.add_items", "write", side_effects=True)
    rig.permissions.add(RuleRequest(agent_id="*", tool="project.*", decision="deny"))
    assert rig.check(t) == "deny"
    rig.permissions.add(RuleRequest(agent_id="scribe", tool="project.add_items", decision="allow"))
    assert rig.check(t) == "allow"  # exact agent and exact tool beat the glob
    assert rig.check(t, tainted=True) == "ask"  # still asks after untrusted text…
    rig.permissions.add(
        RuleRequest(agent_id="scribe", tool="project.add_items", decision="allow", applies_when_tainted=True)
    )
    rig.permissions.add(RuleRequest(agent_id="scribe", tool="project.add_items", decision="ask"))
    assert rig.check(t, tainted=True) == "ask"  # …and between equal rules the strictest wins
    assert rig.check(tool("mcp.x.y", "write", ask_first=True)) == "ask"
    rig.permissions.add(RuleRequest(agent_id="scribe", tool="mcp.x.y", decision="allow"))
    assert rig.check(tool("mcp.x.y", "write", ask_first=True)) == "allow"  # your rule answers for MCP tools
    assert sum(1 for e in rig.audited if e["action"] == "permission.changed") == 5


def test_expired_rules_no_longer_apply(rig: Rig) -> None:
    rig.permissions.add(RuleRequest(tool="vault.search", decision="deny", expires_at="2000-01-01T00:00:00.000Z"))
    assert rig.check(tool("vault.search")) == "allow"


def test_only_you_change_rules_and_caps(rig: Rig) -> None:
    with pytest.raises(PermissionError):
        rig.permissions.add(RuleRequest(tool="x", decision="allow"), actor="agent:core")
    with pytest.raises(PermissionError):
        rig.budget.set_caps(BudgetCaps(monthly_cap_usd=100), actor="agent:core")
    with pytest.raises(ValueError):
        rig.permissions.add_from({"tool": "x; drop table", "decision": "allow"})
    rule = rig.permissions.add(RuleRequest(tool="x", decision="allow"))
    with pytest.raises(PermissionError):
        rig.permissions.remove(rule.id, actor="agent:core")


def test_the_kill_switch_refuses_everything(rig: Rig) -> None:
    rig.killswitch.set(True, via="test")
    assert rig.halted == [True]
    state = TaskState(task_id="t", agent_id="scribe")
    assert rig.policy.check_llm(agent(), state).verdict == "deny"
    assert rig.check(tool("vault.search")) == "deny"
    rig.permissions.add(RuleRequest(tool="vault.search", decision="allow"))
    assert rig.check(tool("vault.search")) == "deny"  # no rule overrides it
    assert ("killswitch.engaged", rig.killswitch.status()) in rig.events
    assert any(e["action"] == "killswitch" for e in rig.audited)
    rig.killswitch.set(False, via="test")
    assert rig.check(tool("vault.search")) == "allow" and rig.halted == [True, False]


def test_limits_are_checked_before_every_model_call(rig: Rig) -> None:
    a = agent(max_steps=2, max_tokens=100, timeout_s=60)
    assert rig.policy.check_llm(a, TaskState("t", "scribe")).verdict == "allow"
    assert rig.policy.check_llm(a, TaskState("t", "scribe", steps_used=2)).verdict == "deny"
    assert rig.policy.check_llm(a, TaskState("t", "scribe", tokens_out=100)).verdict == "deny"
    late = TaskState("t", "scribe", started=0.0)  # started at monotonic 0: long ago
    assert rig.policy.check_llm(a, late).verdict == "deny"


def test_budget_caps_stop_paid_calls_and_warn_on_the_way(rig: Rig) -> None:
    state = TaskState("t", "scribe")
    assert rig.budget.cap == 0
    assert rig.policy.check_llm(agent(), state).verdict == "allow"  # free local calls are always fine
    assert rig.policy.check_llm(agent(), state, estimate_usd=0.01).verdict == "deny"  # $0 cap: nothing paid
    rig.budget.set_caps(BudgetCaps(monthly_cap_usd=10))
    rig.spend(5.5)
    assert rig.policy.check_llm(agent(), state, estimate_usd=0.1).verdict == "allow"
    assert [e for e, _p in rig.events if e == "budget.warning"] == ["budget.warning"]  # 50 %
    rig.spend(4.0)
    decision = rig.policy.check_llm(agent(), state, estimate_usd=1.0)
    assert decision.verdict == "deny" and "$10.00" in decision.reason
    assert ("budget.cap_reached", {"cap_usd": 10.0, "spent_usd": 9.5}) in rig.events
    status = rig.budget.status()
    assert status.spent_usd == pytest.approx(9.5) and status.monthly_cap_usd == 10


def test_permission_rules_table_is_only_written_here(rig: Rig) -> None:
    # A sanity check on the schema the store relies on.
    columns = {r["name"] for r in rig.conn.execute("PRAGMA table_info(permission_rules)")}
    assert {"agent_id", "tool", "decision", "applies_when_tainted", "expires_at"} <= columns
    assert isinstance(rig.conn, sqlite3.Connection)
