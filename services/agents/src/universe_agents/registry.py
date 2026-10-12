"""Agent definitions loaded from agents/*.yaml (SPEC §8). The YAML is the source of truth."""

import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

COLOR_TOKENS = {"cyan", "violet", "amber", "rose", "green", "blue", "slate"}
_HEX = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ID = re.compile(r"^[a-z][a-z0-9-]{1,31}$")


class AgentLimits(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_steps: int = Field(ge=1, le=200)
    max_tokens: int = Field(ge=64, le=1_000_000)
    timeout_s: int = Field(ge=1, le=3600)


class AgentTrigger(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: str | None = None
    schedule: str | None = None
    manual: bool | None = None


class AgentDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    purpose: str
    model: str  # router tier name, e.g. "local-fast"
    escalate_to: str | None = None
    voice: str | None = None
    color: str
    icon: str | None = None
    tools: list[str] = Field(default_factory=list)
    permission_tier: Literal["read", "write", "system"]
    memory: list[str] = Field(default_factory=list)
    triggers: list[AgentTrigger] = Field(default_factory=list)
    limits: AgentLimits
    requires_approval: list[str] = Field(default_factory=list)
    prompt: str  # path relative to the agents directory
    system_prompt: str = ""  # filled in from `prompt` at load time

    @field_validator("id")
    @classmethod
    def _id(cls, value: str) -> str:
        if not _ID.match(value):
            raise ValueError("id must be lowercase letters, digits or '-', 2–32 chars")
        return value

    @field_validator("color")
    @classmethod
    def _color(cls, value: str) -> str:
        if value not in COLOR_TOKENS and not _HEX.match(value):
            raise ValueError(f"color must be a #RRGGBB hex or one of {sorted(COLOR_TOKENS)}")
        return value


class AgentConfigError(ValueError):
    pass


def load_agent(path: Path) -> AgentDefinition:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AgentConfigError(f"{path.name}: {exc}") from exc
    if not isinstance(raw, dict):
        raise AgentConfigError(f"{path.name}: expected a mapping at the top level")
    try:
        agent = AgentDefinition.model_validate(raw)
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors())
        raise AgentConfigError(f"{path.name}: {problems}") from exc
    if agent.id != path.stem:
        raise AgentConfigError(f"{path.name}: id '{agent.id}' must match the file name")
    prompt_path = (path.parent / agent.prompt).resolve()
    if path.parent.resolve() not in prompt_path.parents:
        raise AgentConfigError(f"{path.name}: prompt must live inside the agents directory")
    try:
        agent.system_prompt = prompt_path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise AgentConfigError(f"{path.name}: cannot read prompt {agent.prompt}: {exc}") from exc
    return agent


def load_agents(directory: Path) -> dict[str, AgentDefinition]:
    agents = {}
    for path in sorted(directory.glob("*.yaml")):
        agent = load_agent(path)
        agents[agent.id] = agent
    return agents
