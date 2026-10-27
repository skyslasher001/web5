"""The policy engine: every agent model call and tool call is decided here (ARCHITECTURE.md §7.3). PROTECTED CORE.

Order of checks for a tool call:
1. kill switch: everything is refused while it's engaged;
2. tier gate: a tool's tier must not exceed the agent's `permission_tier`;
3. your rules (`permission_rules`): allow / ask / deny, most specific first;
4. taint: once untrusted text is in a task, tools with side effects or network access ask first, unless a
   rule explicitly applies when tainted;
5. defaults: read → allow, write → ask if listed in the agent's `requires_approval`, otherwise allow,
   system → always ask, and tools marked `ask_first` (MCP servers) → ask.
Before every model call: kill switch, budget caps, and the agent's step, token and time limits.
"""

from fnmatch import fnmatchcase
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

from universe_agents.registry import AgentDefinition
from universe_agents.runtime import Decision, TaskState
from universe_agents.tools import TIER_RANK, Tool
from universe_core.protected.budget import Budget
from universe_core.protected.killswitch import KillSwitch
from universe_core.protected.permissions import PermissionStore

if TYPE_CHECKING:
    from universe_core.context import CoreContext

KILLED = "The kill switch is on: agents are stopped until you release it"


Risk = Literal["low", "medium", "high"]


def _risk(tool: Tool) -> Risk:
    if tool.tier == "system":
        return "high"
    if tool.side_effects or tool.network:
        return "medium"
    return "low"


class PolicyEngine:
    def __init__(self, *, killswitch: KillSwitch, permissions: PermissionStore, budget: Budget) -> None:
        self.killswitch = killswitch
        self.permissions = permissions
        self.budget = budget

    def check_llm(self, agent: AgentDefinition, task: TaskState, estimate_usd: float = 0.0) -> Decision:
        if self.killswitch.engaged:
            return Decision("deny", KILLED, "high")
        limits = agent.limits
        if task.steps_used >= limits.max_steps:
            return Decision("deny", f"{agent.name} used all {limits.max_steps} steps for this task")
        if task.tokens_out >= limits.max_tokens:
            return Decision("deny", f"{agent.name} reached its limit of {limits.max_tokens} tokens for this task")
        if task.elapsed_s >= limits.timeout_s:
            return Decision("deny", f"{agent.name} ran out of time ({limits.timeout_s} s) for this task")
        allowed, why = self.budget.allows(estimate_usd)
        if not allowed:
            return Decision("deny", why, "high")
        return Decision("allow")

    def check_tool(self, agent: AgentDefinition, tool: Tool, args: BaseModel, task: TaskState) -> Decision:
        risk = _risk(tool)
        if self.killswitch.engaged:
            return Decision("deny", KILLED, "high")
        if TIER_RANK[tool.tier] > TIER_RANK[agent.permission_tier]:
            return Decision(
                "deny", f"{tool.name} needs the '{tool.tier}' tier; {agent.name} has '{agent.permission_tier}'", risk
            )
        risky_when_tainted = task.tainted and (tool.side_effects or tool.network)
        rule = self.permissions.match(agent.id, tool.name)
        if rule is not None:
            if rule.decision == "deny":
                return Decision("deny", "You set a rule that refuses this", risk, rule.id)
            if rule.decision == "ask":
                return Decision("ask", "You set a rule to be asked first", risk, rule.id)
            if risky_when_tainted and not rule.applies_when_tainted:
                return Decision("ask", "The task has read untrusted text, so actions need your OK", risk, rule.id)
            return Decision("allow", "Allowed by your rule", risk, rule.id)
        if tool.tier == "system":
            return Decision("ask", "System actions always need your OK", risk)
        if tool.ask_first:
            return Decision("ask", "This tool comes from an MCP server: you're asked until you set a rule", risk)
        if risky_when_tainted:
            return Decision("ask", "The task has read untrusted text, so actions need your OK", risk)
        if tool.tier == "write" and any(fnmatchcase(tool.name, p) for p in agent.requires_approval):
            return Decision("ask", f"{agent.name} needs your OK for {tool.name}", risk)
        return Decision("allow", "", risk)


def build(ctx: "CoreContext") -> PolicyEngine:
    """Called by Core at startup (universe_core.context.load_safety)."""

    def audit(**entry: Any) -> None:
        ctx.audit.append(**entry)

    def publish(event_type: str, payload: dict[str, Any]) -> None:
        ctx.bus.publish(event_type, payload, actor="system")

    def on_change(engaged: bool) -> None:
        ctx.gate.killed = engaged
        if engaged and ctx.engine is not None:
            ctx.engine.halt_all("The kill switch is on")

    return PolicyEngine(
        killswitch=KillSwitch(ctx.settings.data_dir, audit=audit, publish=publish, on_change=on_change),
        permissions=PermissionStore(ctx.dbs.universe, audit),
        budget=Budget(ctx.dbs.universe, audit, publish),
    )
