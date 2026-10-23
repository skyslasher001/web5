from pathlib import Path

import pytest

from tests.conftest import REPO
from universe_agents.registry import AgentConfigError, load_agent, load_agents

VALID = """\
id: scribe
name: Scribe
purpose: Captures notes.
model: local-fast
color: "#7FD4FF"
tools: []
permission_tier: write
limits: {max_steps: 5, max_tokens: 1000, timeout_s: 60}
prompt: prompts/scribe.md
"""


def _write(tmp_path: Path, text: str, name: str = "scribe") -> Path:
    (tmp_path / "prompts").mkdir(exist_ok=True)
    (tmp_path / "prompts" / f"{name}.md").write_text("You are Scribe.")
    path = tmp_path / f"{name}.yaml"
    path.write_text(text)
    return path


def test_repo_agents_load() -> None:
    agents = load_agents(REPO / "agents")
    core = agents["core"]
    assert core.model == "local-fast"
    assert core.permission_tier == "write"
    assert "Core" in core.system_prompt


def test_valid_definition(tmp_path: Path) -> None:
    agent = load_agent(_write(tmp_path, VALID))
    assert agent.system_prompt == "You are Scribe."
    assert agent.limits.max_steps == 5


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('color: "#7FD4FF"', "color: chartreuse"), "color"),
        (("permission_tier: write", "permission_tier: root"), "permission_tier"),
        (("model: local-fast", "model: local-fast\nsurprise: 1"), "surprise"),
        (("id: scribe", "id: other"), "must match the file name"),
        (("prompt: prompts/scribe.md", "prompt: ../../etc/passwd"), "inside the agents directory"),
        (("max_steps: 5", "max_steps: 0"), "max_steps"),
    ],
)
def test_invalid_definitions_name_the_problem(tmp_path: Path, change: tuple[str, str], message: str) -> None:
    with pytest.raises(AgentConfigError, match=message):
        load_agent(_write(tmp_path, VALID.replace(*change)))
