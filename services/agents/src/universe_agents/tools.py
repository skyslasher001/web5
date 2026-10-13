"""The tool interface every agent capability goes through (ARCHITECTURE.md §5.4).

A tool declares its tier and its effects; the policy engine (protected core) decides from those whether a
call runs, asks you first, or is refused. Tools never decide that themselves.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

Tier = Literal["read", "write", "system"]
TIER_RANK: dict[str, int] = {"read": 0, "write": 1, "system": 2}


@dataclass
class ToolResult:
    content: str  # what the model sees
    data: dict[str, Any] = field(default_factory=dict)  # structured result for traces and the UI
    untrusted: bool = False  # text from files, the web or MCP: taints the task (§7.3)
    error: bool = False


@dataclass
class ToolContext:
    task_id: str
    agent_id: str
    actor: str  # "agent:<id>"
    tainted: bool


@dataclass
class Tool:
    name: str  # "vault.search"
    description: str
    input_model: type[BaseModel]
    tier: Tier
    run: Callable[[BaseModel, ToolContext], Awaitable[ToolResult]]
    side_effects: bool = False  # False = safe to call from a tainted context
    network: bool = False  # goes beyond this machine (through the egress gate)
    timeout_s: float = 30.0
    summarize: Callable[[BaseModel], str] | None = None  # one line for approval cards

    def schema(self) -> dict[str, Any]:
        """The OpenAI tool-calling description of this tool."""
        parameters = self.input_model.model_json_schema()
        parameters.pop("title", None)
        return {
            "type": "function",
            "function": {"name": wire_name(self.name), "description": self.description, "parameters": parameters},
        }

    def parse(self, arguments: dict[str, Any]) -> BaseModel:
        return self.input_model.model_validate(arguments)

    def describe(self, args: BaseModel) -> str:
        if self.summarize is not None:
            return self.summarize(args)
        return f"{self.name}({args.model_dump_json()})"


def wire_name(name: str) -> str:
    """Tool names as models see them: OpenAI-style names allow [a-zA-Z0-9_-], so "vault.search" → "vault__search"."""
    return name.replace(".", "__")


def validation_message(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or 'arguments'}: {e['msg']}" for e in exc.errors())


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def add(self, tool: Tool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"tool {tool.name} is already registered")
        self._tools[tool.name] = tool

    def remove_prefix(self, prefix: str) -> None:
        for name in [n for n in self._tools if n.startswith(prefix)]:
            del self._tools[name]

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def by_wire_name(self, wire: str) -> Tool | None:
        for tool in self._tools.values():
            if wire_name(tool.name) == wire:
                return tool
        return None

    def names(self) -> list[str]:
        return sorted(self._tools)

    def for_agent(self, patterns: list[str]) -> list[Tool]:
        """Tools an agent's YAML grants: exact names or `prefix.*` globs."""
        out = []
        for tool in self._tools.values():
            if any(p == tool.name or (p.endswith(".*") and tool.name.startswith(p[:-1])) for p in patterns):
                out.append(tool)
        return sorted(out, key=lambda t: t.name)
