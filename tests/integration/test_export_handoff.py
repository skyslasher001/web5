"""The handoff package (scripts/export_handoff.py, docs/HANDOFF.md): built from the committed HEAD, it holds the
rules, the brief, the owner's decisions, every document, the code, the source and the history, and nothing
that isn't in git."""

import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "export_handoff.py"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("export_handoff", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["export_handoff"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def package(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, ModuleType]:
    exporter = load()
    folder, archive = exporter.build(ROOT, tmp_path_factory.mktemp("handoff"))
    return folder, archive, exporter


def tracked_at_head() -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-tree", "-r", "--name-only", "HEAD"], capture_output=True)
    return set(out.stdout.decode().split())


def test_the_package_has_every_part_and_the_zip_holds_them(package: tuple[Path, Path, ModuleType]) -> None:
    folder, archive, _ = package
    names = {p.name for p in folder.iterdir()}
    expected = {"00-START-HERE.md", "universe-brief.md", "universe-docs.md", "universe-code.md",
                "universe-source.zip", "SHA256SUMS.txt"}  # fmt: skip
    assert expected <= names
    with zipfile.ZipFile(archive) as zf:
        assert {Path(n).name for n in zf.namelist()} == names
    for line in (folder / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest, name


def test_the_brief_carries_the_rules_the_brief_and_the_owners_words(package: tuple[Path, Path, ModuleType]) -> None:
    brief = (package[0] / "universe-brief.md").read_text(encoding="utf-8")
    for path in ("AGENTS.md", "docs/handoff/PROJECT-BRIEF.md", "docs/handoff/DECISIONS.md", "docs/HANDOFF.md"):
        assert f"## File: `{path}`" in brief, path
    assert "Protected core — never modify" in brief
    assert "Read SPEC.md and deliver Phase 0" in brief  # the owner's first message, verbatim
    assert "approved use defaults initiate phase 1" in brief


def test_the_docs_pack_has_every_document(package: tuple[Path, Path, ModuleType]) -> None:
    docs = (package[0] / "universe-docs.md").read_text(encoding="utf-8")
    wanted = [p for p in tracked_at_head() if p.startswith("docs/") and p.endswith(".md") and "phase-5/" not in p]
    assert "## File: `SPEC.md`" in docs
    for path in wanted:
        assert f"## File: `{path}`" in docs, path
    assert docs.index("`AGENTS.md`") < docs.index("## File: `SPEC.md`")  # the rules come first


def test_the_code_pack_has_the_source_but_not_lockfiles_or_generated_files(
    package: tuple[Path, Path, ModuleType],
) -> None:
    code = (package[0] / "universe-code.md").read_text(encoding="utf-8")
    assert "## File: `services/core/src/universe_core/app.py`" in code
    assert "## File: `apps/ui/src/hud/ForgePanel.tsx`" in code
    assert "## File: `scripts/export_handoff.py`" in code
    for left_out in ("pnpm-lock.yaml", "uv.lock", "packages/shared-types/src/api.ts"):
        assert f"## File: `{left_out}`" not in code


def test_the_source_zip_is_exactly_what_git_tracks(package: tuple[Path, Path, ModuleType]) -> None:
    with zipfile.ZipFile(package[0] / "universe-source.zip") as zf:
        files = {n.removeprefix("universe/") for n in zf.namelist() if not n.endswith("/")}
    assert files == tracked_at_head()
    assert not any(f.startswith(("node_modules/", ".venv/", "dist/")) or f.endswith(".env") for f in files)


def test_start_here_says_where_things_stand_and_what_to_paste(package: tuple[Path, Path, ModuleType]) -> None:
    folder, _, _ = package
    text = (folder / "00-START-HERE.md").read_text(encoding="utf-8")
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True).stdout.decode().strip()
    assert head in text
    assert "**Current phase:** Phase" in text
    assert "You're working on UNIVERSE" in text  # the start prompt from docs/HANDOFF.md
    assert "claude/phase-0-delivery-zuqlfx" in text


def test_the_history_bundle_clones_or_says_why_it_is_missing(
    package: tuple[Path, Path, ModuleType], tmp_path: Path
) -> None:
    folder, _, _ = package
    shallow = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--is-shallow-repository"], capture_output=True)
    start = (folder / "00-START-HERE.md").read_text(encoding="utf-8")
    bundle = folder / "universe-history.bundle"
    if shallow.stdout.decode().strip() == "true":  # CI checkouts can be shallow: no partial history is shipped
        assert not bundle.exists() and "shallow" in start
        return
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(bundle), str(clone)], check=True)
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True).stdout
    assert subprocess.run(["git", "-C", str(clone), "cat-file", "-e", head.decode().strip()]).returncode == 0


def test_a_file_containing_backticks_gets_a_longer_fence(package: tuple[Path, Path, ModuleType]) -> None:
    exporter = package[2]
    section = exporter.fenced("x.md", "text\n````\ninner\n````\n")
    assert "\n`````markdown\n" in section and section.rstrip().endswith("`````")
