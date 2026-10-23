"""The agent loop's tool-call path (universe_agents.runtime): what it records when a tool misbehaves."""

from pathlib import Path
from typing import Any, cast

from pydantic import BaseModel

from universe_agents.providers import ToolCall
from universe_agents.registry import AgentDefinition, load_agent
from universe_agents.router import ModelRouter
from universe_agents.runtime import AgentRuntime, Decision, ModelClient, TaskState
from universe_agents.tools import Tool, ToolContext, ToolRegistry, ToolResult

AGENTS = Path(__file__).resolve().parents[2] / "agents"


class NoArgs(BaseModel):
    pass


class AllowAll:
    def check_llm(self, agent: AgentDefinition, task: TaskState) -> Decision:
        return Decision("allow")

    def check_tool(self, agent: AgentDefinition, tool: Tool, args: BaseModel, task: TaskState) -> Decision:
        return Decision("allow", rule_id="test")


class RecordingHooks:
    def __init__(self) -> None:
        self.steps: list[tuple[str, dict[str, Any]]] = []
        self.audits: list[tuple[str, dict[str, Any], str]] = []

    def step(self, state: TaskState, kind: str, **fields: Any) -> None:
        self.steps.append((kind, fields))

    def update(self, state: TaskState, **fields: Any) -> None:
        pass

    async def ask(
        self, state: TaskState, agent: AgentDefinition, tool: Tool, args: BaseModel, decision: Decision
    ) -> bool:
        return False

    def emit(self, state: TaskState, event_type: str, payload: dict[str, Any]) -> None:
        pass

    def audit(self, state: TaskState, action: str, details: dict[str, Any], outcome: str = "ok") -> None:
        self.audits.append((action, details, outcome))

    def usage(self, state: TaskState, model: str, tokens_in: int, tokens_out: int) -> None:
        pass

    def context(self, agent: AgentDefinition, text: str) -> str:
        return ""


async def test_a_tool_that_crashes_is_still_audited_and_traced() -> None:
    """Regression: an exception a tool didn't anticipate (say a KeyError deep in its code, or sqlite3.Error)
    escaped the loop before the `tool.call` audit record and the `tool_result` step were written, so the audit
    log had no trace of a call that ran."""

    async def crash(_args: BaseModel, _ctx: ToolContext) -> ToolResult:
        raise RuntimeError("the index is corrupt")

    registry = ToolRegistry()
    registry.add(Tool("vault.search", "Search", NoArgs, "read", crash))
    runtime = AgentRuntime(
        router=cast(ModelRouter, None), model=cast(ModelClient, None), tools=registry, policy=AllowAll()
    )
    agent = load_agent(AGENTS / "navigator.yaml")
    hooks = RecordingHooks()
    state = TaskState(task_id="t1", agent_id=agent.id)
    call = ToolCall(id="c1", name="vault__search", arguments={}, raw_arguments="{}")

    content = await runtime._call(agent, state, call, {"vault.search"}, hooks)

    assert content.startswith("Error:") and "the index is corrupt" in content
    assert [(a, d["tool"], o) for a, d, o in hooks.audits] == [("tool.call", "vault.search", "error")]
    kinds = [kind for kind, _ in hooks.steps]
    assert kinds == ["tool_call", "tool_result"]
    assert '"error": true' in hooks.steps[-1][1]["result"]
