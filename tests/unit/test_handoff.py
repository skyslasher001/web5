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


def test_the_brief_the_decisions_and_the_index_exist_and_point_at_each_other() -> None:
    brief = (ROOT / "docs" / "handoff" / "PROJECT-BRIEF.md").read_text(encoding="utf-8")
    decisions = (ROOT / "docs" / "handoff" / "DECISIONS.md").read_text(encoding="utf-8")
    index = (ROOT / "llms.txt").read_text(encoding="utf-8")
    assert "DECISIONS.md" in brief and "PROJECT-BRIEF.md" in decisions
    assert "docs/handoff/PROJECT-BRIEF.md" in index and "AGENTS.md" in index
    assert "Read SPEC.md and deliver Phase 0" in decisions  # the owner's words are kept verbatim


def test_the_handoff_lists_every_pointer_file() -> None:
    handoff = (ROOT / "docs" / "HANDOFF.md").read_text(encoding="utf-8")
    for name in ("CLAUDE.md", ".github/copilot-instructions.md", ".gemini/settings.json", ".aider.conf.yml"):
        assert name in handoff, name


def test_relative_links_in_the_guides_resolve() -> None:
    guides = [
        ROOT / "AGENTS.md",
        ROOT / "llms.txt",
        ROOT / "docs" / "HANDOFF.md",
        ROOT / ".github" / "copilot-instructions.md",
    ]
    for doc in [*guides, *sorted((ROOT / "docs" / "handoff").glob("*.md"))]:
        text = doc.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#\s]+)(?:#[^)]*)?\)", text):
            if "://" in target:
                continue
            assert (doc.parent / target).exists(), f"{doc.name} links to missing {target}"
