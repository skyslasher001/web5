"""Forge's core (Phase 5, ADR-0014): protected paths, worktree guards, verification and triage, on a scratch repo."""

from pathlib import Path

import pytest

from tests.support.forge_repo import FIXED, REPRO_TEST, make_repo
from universe_common.sqlite import migrate_up
from universe_core.db import Databases
from universe_core.forge import DAILY_CAP, Forge, ForgeError, ProtectedPaths
from universe_core.forge_verify import Report, Verifier, scrubbed_env


@pytest.fixture
def forge(tmp_path: Path) -> Forge:
    Databases.open(tmp_path / "index").close()  # migrate
    return Forge(tmp_path / "index" / "universe.db", make_repo(tmp_path), tmp_path / "data")


def test_protected_paths_follow_the_manifest() -> None:
    paths = ProtectedPaths.load(Path(__file__).resolve().parents[2])  # the real protected-core.txt
    for protected in (
        "protected-core.txt",
        "services/supervisor/src/universe_supervisor/control.py",
        "services/core/src/universe_core/protected/policy.py",
        "agents/forge.yaml",
        "tests/protected/test_invariants.py",
        ".github/workflows/ci.yml",
        "services/supervisor",
    ):
        assert paths.matches(protected), protected
    for free in ("services/core/src/universe_core/forge.py", "agents/librarian.yaml", "apps/ui/src/App.tsx"):
        assert not paths.matches(free), free


def test_a_worktree_takes_writes_only_where_forge_may_write(forge: Forge) -> None:
    proposal, tree = forge.start_proposal(title="Fix add", issue_id=None, task_id="t1")
    assert proposal.branch == f"forge/{proposal.id}" and proposal.status == "draft"
    assert tree.write("calc/__init__.py", FIXED) == "calc/__init__.py"
    for bad, why in [
        ("../outside.txt", "outside"),
        ("/etc/passwd", "relative"),
        (".git/config", ".git"),
        ("services/supervisor/run.py", "protected"),
        ("protected-core.txt", "protected"),
        ("agents/forge.yaml", "protected"),
    ]:
        with pytest.raises(ForgeError, match=why):
            tree.write(bad, "x")
    head = tree.commit("Fix add")
    assert [f.path for f in tree.changes()] == ["calc/__init__.py"]
    assert "-    return a - b" in tree.diff() and "+    return a + b" in tree.diff()
    # The owner's checkout is untouched: the fix lives only on the branch.
    assert "return a - b" in (forge.require_repo() / "calc" / "__init__.py").read_text()
    assert forge.proposal_for_task("t1").id == proposal.id  # type: ignore[union-attr]
    assert head != proposal.base_commit


def test_the_repro_test_must_fail_on_the_old_code_and_pass_on_the_new(forge: Forge) -> None:
    proposal, tree = forge.start_proposal(title="Fix add", issue_id=None, task_id="t2")
    tree.write("tests/test_add.py", REPRO_TEST)
    tree.commit("test first")
    verifier = Verifier(forge.require_repo())
    base = forge.base_checkout(proposal.base_commit)
    # The test alone, without the fix: it fails on base and still fails here, so this isn't verified.
    only_test = verifier.repro(base, tree.path, "tests/test_add.py::test_add_adds")
    assert only_test["fails_on_base"] and not only_test["passes_on_head"]
    tree.write("calc/__init__.py", FIXED)
    tree.commit("fix")
    report = Report(repro=verifier.repro(base, tree.path, "tests/test_add.py::test_add_adds"))
    report.checks = verifier.checks(tree.path, ["calc/__init__.py", "tests/test_add.py"])
    assert report.repro["fails_on_base"] and report.repro["passes_on_head"], report.summary()
    assert report.passed, report.summary()
    assert any(c.name == "pytest (full suite)" for c in report.checks)
    assert not (base / "tests" / "test_add.py").exists()  # the base checkout stays pristine


def test_a_test_that_passes_on_the_old_code_proves_nothing(forge: Forge) -> None:
    proposal, tree = forge.start_proposal(title="No-op", issue_id=None, task_id="t3")
    tree.write("tests/test_trivial.py", "def test_ok() -> None:\n    assert True\n")
    tree.commit("a test that never failed")
    verifier = Verifier(forge.require_repo())
    repro = verifier.repro(forge.base_checkout(proposal.base_commit), tree.path, "tests/test_trivial.py")
    assert not repro["fails_on_base"]
    assert not Report(repro=repro).passed


def test_checks_run_without_secrets_or_network(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("UNIVERSE_SESSION_TOKEN", "secret")
    monkeypatch.setenv("GITHUB_TOKEN", "secret")
    env = scrubbed_env(tmp_path, tmp_path / "home")
    assert "UNIVERSE_SESSION_TOKEN" not in env and "GITHUB_TOKEN" not in env
    assert env["UNIVERSE_OFFLINE"] == "1" and env["HTTPS_PROXY"].endswith(":9")
    assert env["HOME"] == str(tmp_path / "home")


def test_issues_group_reports_and_the_daily_cap_holds(forge: Forge) -> None:
    first = forge.report("The photo viewer froze when I opened a PDF")
    again = forge.report("The photo viewer froze when I opened a PDF")
    assert again.id == first.id and again.count == 2  # duplicates collapse onto one issue
    other = forge.report("Search is slow")
    assert {i.id for i in forge.issues("open")} == {first.id, other.id}
    assert forge.issues()[0].id == first.id  # ranked: seen twice
    for n in range(DAILY_CAP):
        forge.start_proposal(title=f"p{n}", issue_id=None, task_id=f"cap{n}")
    with pytest.raises(ForgeError, match="rate limit"):
        forge.start_proposal(title="one too many", issue_id=None, task_id="cap-x")


def test_errors_and_dead_jobs_become_issues(forge: Forge, tmp_path: Path) -> None:
    conn = forge._conn
    conn.execute(
        "INSERT INTO errors (id, fingerprint, service, kind, message, stack, first_seen, last_seen, count)"
        " VALUES ('e1', 'fp1', 'core', 'ZeroDivisionError', 'division by zero', 'Traceback…',"
        " '2026-10-14T00:00:00.000Z', '2026-10-14T00:00:00.000Z', 3)"
    )
    assert forge.sync_issues() == 1
    assert forge.sync_issues() == 0  # nothing new
    [issue] = forge.issues()
    assert issue.source == "error" and issue.count == 3 and "ZeroDivisionError" in issue.title
    assert "Traceback" in issue.detail


def test_migrations_up_to_date(tmp_path: Path) -> None:
    import universe_core

    conn = Databases.open(tmp_path / "x").universe
    applied = migrate_up(conn, Path(universe_core.__file__).parent / "migrations" / "universe")
    assert applied == []  # opening the databases applied everything, including 0007_forge
