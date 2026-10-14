"""The portable handoff (docs/HANDOFF.md): every AI tool's instruction file points to AGENTS.md, and the
documents AGENTS.md and the handoff send readers to exist."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_every_tools_instruction_file_points_to_agents_md() -> None:
    assert (ROOT / "CLAUDE.md").read_text(encoding="utf-8").startswith("@AGENTS.md")
    assert "AGENTS.md" in (ROOT / ".github" / "copilot-instructions.md").read_text(encoding="utf-8")
    gemini = json.loads((ROOT / ".gemini" / "settings.json").read_text(encoding="utf-8"))
    assert gemini["context"]["fileName"][0] == "AGENTS.md"
    aider = (ROOT / ".aider.conf.yml").read_text(encoding="utf-8")
    assert re.search(r"^read:\s*\[?\s*AGENTS\.md", aider, re.MULTILINE)


def test_the_handoff_lists_every_pointer_file() -> None:
    handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    for name in ("CLAUDE.md", ".github/copilot-instructions.md", ".gemini/settings.json", ".aider.conf.yml"):
        assert name in handoff, name


def test_relative_links_in_the_guides_resolve() -> None:
    for doc in (ROOT / "AGENTS.md", ROOT / "docs" / "HANDOFF.md", ROOT / ".github" / "copilot-instructions.md"):
        text = doc.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if "://" in target:
                continue
            assert (doc.parent / target).exists(), f"{doc.name} links to missing {target}"
