"""The supervisor's releases (Phase 5, ADR-0014): what it applies, what it refuses, and how it rolls back. Runs on
a scratch git repository with an injected bug, never on the real checkout."""

import hashlib
import subprocess
from pathlib import Path

import pytest

from tests.support.forge_repo import FIXED, REPRO_TEST, head, make_repo
from universe_supervisor.releases import ReleaseError, Releases


def sh(repo: Path, *args: str) -> str:
    env_args = ["-c", "user.name=T", "-c", "user.email=t@example.com"]
    return subprocess.run(["git", *env_args, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


def forge_branch(repo: Path, name: str = "forge/p1", files: dict[str, str] | None = None) -> dict[str, str]:
    """What Forge leaves behind: a branch with a verified commit on top of HEAD."""
    base = head(repo)
    sh(repo, "checkout", "-q", "-b", name)
    for rel, content in (files or {"calc/__init__.py": FIXED, "tests/test_add.py": REPRO_TEST}).items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(content, encoding="utf-8")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "Forge: fix add")
    tip = head(repo)
    sh(repo, "checkout", "-q", "main")
    diff = sh(repo, "diff", "--no-color", "--text", f"{base}..{tip}")
    return {
        "proposal_id": "p1",
        "branch": name,
        "base_commit": base,
        "head_commit": tip,
        "diff_sha": hashlib.sha256(diff.encode()).hexdigest(),
        "title": "Fix add",
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_repo(tmp_path)


def test_an_approved_change_is_fast_forwarded_tagged_and_watched(repo: Path, tmp_path: Path) -> None:
    releases = Releases(repo, tmp_path / "releases.json")
    proposal = forge_branch(repo)
    release = releases.apply(**proposal)
    assert release["status"] == "watching" and release["tag"] == "universe/release-1"
    assert head(repo) == proposal["head_commit"]
    assert "return a + b" in (repo / "calc" / "__init__.py").read_text()
    assert "universe/release-1" in sh(repo, "tag") and "universe/pre-release-1" in sh(repo, "tag")
    assert releases.list()[0]["current"] is True
    # Another apply waits until this one settles.
    with pytest.raises(ReleaseError, match="still being watched"):
        releases.apply(**forge_branch(repo, "forge/p2", {"calc/extra.py": "X = 1\n"}))
    releases.settle(release["tag"])
    assert Releases(repo, tmp_path / "releases.json").list()[0]["status"] == "good"  # state survives a restart


@pytest.mark.parametrize(
    ("tamper", "message"),
    [
        ("dirty", "uncommitted changes"),
        ("moved_branch", "branch moved"),
        ("moved_main", "code moved on"),
        ("wrong_sha", "hash differs"),
        ("not_forge", "Only Forge branches"),
    ],
)
def test_anything_that_differs_from_what_you_approved_is_refused(
    repo: Path, tmp_path: Path, tamper: str, message: str
) -> None:
    releases = Releases(repo, tmp_path / "releases.json")
    proposal = forge_branch(repo)
    if tamper == "dirty":
        (repo / "calc" / "__init__.py").write_text("# my unsaved work\n", encoding="utf-8")
    elif tamper == "moved_branch":
        sh(repo, "checkout", "-q", proposal["branch"])
        (repo / "calc" / "sneaky.py").write_text("x = 1\n", encoding="utf-8")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-q", "-m", "after verification")
        sh(repo, "checkout", "-q", "main")
    elif tamper == "moved_main":
        (repo / "README.md").write_text("owner's commit\n", encoding="utf-8")
        sh(repo, "add", "-A")
        sh(repo, "commit", "-q", "-m", "owner")
    elif tamper == "wrong_sha":
        proposal["diff_sha"] = "0" * 64
    elif tamper == "not_forge":
        sh(repo, "branch", "feature/x", proposal["head_commit"])
        proposal["branch"] = "feature/x"
    before = head(repo)
    with pytest.raises(ReleaseError, match=message):
        releases.apply(**proposal)
    assert head(repo) == before  # nothing applied


def test_protected_core_is_refused_by_the_supervisors_own_manifest_copy(repo: Path, tmp_path: Path) -> None:
    releases = Releases(repo, tmp_path / "releases.json")
    proposal = forge_branch(repo, files={"services/supervisor/run.py": "print('patched')\n"})
    with pytest.raises(ReleaseError, match="protected core"):
        releases.apply(**proposal)
    # Editing the manifest in the checkout doesn't help: the supervisor compares with the copy it started with.
    (repo / "protected-core.txt").write_text("# nothing protected\n", encoding="utf-8")
    sh(repo, "commit", "-q", "-am", "unprotect everything")
    other = forge_branch(repo, "forge/p3", {"calc/extra.py": "X = 1\n"})
    with pytest.raises(ReleaseError, match="changed since the supervisor started"):
        releases.apply(**other)


def test_renaming_a_protected_file_to_an_unprotected_path_is_refused(repo: Path, tmp_path: Path) -> None:
    # git's rename detection would show only the (unprotected) destination; the gate uses --no-renames so the
    # protected source is still seen and the apply is refused.
    releases = Releases(repo, tmp_path / "releases.json")
    base = head(repo)
    sh(repo, "checkout", "-q", "-b", "forge/p1")
    sh(repo, "mv", "services/supervisor/run.py", "calc/run_copy.py")  # git mv: a pure rename
    sh(repo, "commit", "-q", "-m", "sneak a protected file out by renaming it")
    tip = head(repo)
    sh(repo, "checkout", "-q", "main")
    diff = sh(repo, "diff", "--no-color", "--text", f"{base}..{tip}")
    proposal = {
        "proposal_id": "p1", "branch": "forge/p1", "base_commit": base, "head_commit": tip,
        "diff_sha": hashlib.sha256(diff.encode()).hexdigest(), "title": "rename",
    }  # fmt: skip
    with pytest.raises(ReleaseError, match="protected core"):
        releases.apply(**proposal)
    assert head(repo) == base  # nothing applied


def test_rollback_reverts_without_losing_later_commits(repo: Path, tmp_path: Path) -> None:
    releases = Releases(repo, tmp_path / "releases.json")
    release = releases.apply(**forge_branch(repo))
    releases.settle(release["tag"])
    (repo / "NOTES.md").write_text("the owner's own commit after the release\n", encoding="utf-8")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "owner work")
    rolled = releases.rollback(release["tag"], "rolled back by you")
    assert rolled["status"] == "rolled_back"
    assert "return a - b" in (repo / "calc" / "__init__.py").read_text()  # the change is undone
    assert (repo / "NOTES.md").is_file()  # the owner's later commit is kept
    assert "Revert" in sh(repo, "log", "-1", "--format=%s")  # history added, not rewritten
    with pytest.raises(ReleaseError, match="already rolled back"):
        releases.rollback(release["tag"], "again")
    assert releases.list()[0]["current"] is False


@pytest.mark.slow
def test_a_release_that_makes_core_crash_rolls_itself_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.test_supervisor import CONTROL_TOKEN, Harness, core

    repo = make_repo(tmp_path)
    (tmp_path / "sup").mkdir()
    h = Harness(tmp_path / "sup", repo)
    monkeypatch.setenv("FAKE_CORE_CONTROL", str(h.control_file))
    monkeypatch.setenv("FAKE_CORE_ENV_OUT", str(h.env_out))
    monkeypatch.setenv("UNIVERSE_SUPERVISOR_TOKEN", CONTROL_TOKEN)
    try:
        h.run_until(lambda s: core(s)["state"] == "healthy")
        proposal = forge_branch(repo)
        h.set_mode("crash")  # the new code crashes Core
        result = h.sup.apply_release(proposal)
        assert result["ok"], result
        assert head(repo) == proposal["head_commit"]
        h.run_until(lambda _s: h.sup.releases.list()[0]["status"] == "rolled_back", timeout=30)
        rolled = h.sup.releases.list()[0]
        # Crashing at boot puts Core in safe mode; crashing after boot counts crashes. Either rolls back.
        assert rolled["rollback_reason"] in (
            "automatic: Core fell into safe mode after the change",
            "automatic: Core crashed 2 times after the change",
        )
        assert "return a - b" in (repo / "calc" / "__init__.py").read_text()  # back to the old code
        h.set_mode("ok")
        h.run_until(lambda s: core(s)["state"] == "healthy", timeout=30)
        # A refused apply changes nothing and says why.
        refused = h.sup.apply_release({**proposal, "diff_sha": "0" * 64})
        assert refused["ok"] is False and "error" in refused
    finally:
        h.sup.shutdown()


def test_a_rollback_that_conflicts_changes_nothing_and_isnt_retried(repo: Path, tmp_path: Path) -> None:
    # Review 2026-10-21: a conflicting revert left the checkout mid-revert and the watch retried it every tick.
    releases = Releases(repo, tmp_path / "releases.json")
    release = releases.apply(**forge_branch(repo))
    (repo / "calc" / "__init__.py").write_text(FIXED.replace("return a + b", "return b + a  # owner"), encoding="utf-8")
    sh(repo, "commit", "-q", "-am", "the owner edits the same line")
    before = head(repo)
    with pytest.raises(ReleaseError):
        releases.rollback(release["tag"], "automatic: Core crashed 2 times after the change")
    assert head(repo) == before and sh(repo, "status", "--porcelain") == ""  # the checkout is as it was
    assert not (repo / ".git" / "sequencer").exists() and not (repo / ".git" / "REVERT_HEAD").exists()
    saved = Releases(repo, tmp_path / "releases.json").list()[0]
    assert saved["status"] == "rollback_failed" and "conflicted" in saved["rollback_reason"]
    assert releases.watching() is None  # so the watch stops instead of retrying


def test_a_symbolic_link_is_refused(repo: Path, tmp_path: Path) -> None:
    releases = Releases(repo, tmp_path / "releases.json")
    base = head(repo)
    sh(repo, "checkout", "-q", "-b", "forge/p1")
    (repo / "calc" / "env").symlink_to("../../outside")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "a link out of the checkout")
    tip = head(repo)
    sh(repo, "checkout", "-q", "main")
    diff = sh(repo, "diff", "--no-color", "--text", f"{base}..{tip}")
    proposal = {
        "proposal_id": "p1", "branch": "forge/p1", "base_commit": base, "head_commit": tip,
        "diff_sha": hashlib.sha256(diff.encode()).hexdigest(), "title": "link",
    }  # fmt: skip
    with pytest.raises(ReleaseError, match="symbolic link"):
        releases.apply(**proposal)
    assert head(repo) == base


def test_the_approved_hash_covers_binary_content(repo: Path, tmp_path: Path) -> None:
    # Without --text two different "binary" files diff to the same "Binary files differ" line, so one hash
    # would approve either.
    releases = Releases(repo, tmp_path / "releases.json")
    proposal = forge_branch(repo, files={"calc/data.bin": "a\x00b\n"})
    assert "a\x00b" in sh(repo, "diff", "--text", f"{proposal['base_commit']}..{proposal['head_commit']}")
    plain = sh(repo, "diff", "--no-color", f"{proposal['base_commit']}..{proposal['head_commit']}")
    with pytest.raises(ReleaseError, match="hash differs"):
        releases.apply(**{**proposal, "diff_sha": hashlib.sha256(plain.encode()).hexdigest()})
    assert releases.apply(**proposal)["status"] == "watching"


def _supervisor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, repo: Path):
    from tests.integration.test_supervisor import CONTROL_TOKEN, Harness

    (tmp_path / "sup").mkdir()
    h = Harness(tmp_path / "sup", repo)
    monkeypatch.setenv("FAKE_CORE_CONTROL", str(h.control_file))
    monkeypatch.setenv("FAKE_CORE_ENV_OUT", str(h.env_out))
    monkeypatch.setenv("UNIVERSE_SUPERVISOR_TOKEN", CONTROL_TOKEN)
    return h


@pytest.mark.slow
def test_restarts_you_ask_for_dont_roll_a_release_back(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.test_supervisor import core

    repo = make_repo(tmp_path)
    h = _supervisor(tmp_path, monkeypatch, repo)
    try:
        h.run_until(lambda s: core(s)["state"] == "healthy")
        assert h.sup.apply_release(forge_branch(repo))["ok"]
        h.run_until(lambda s: core(s)["state"] == "healthy")
        for n in (2, 3):  # restarts from the System panel (or a model change) during the 30-minute watch
            assert h.sup.restart("core")
            h.run_until(lambda s, n=n: core(s)["state"] == "healthy" and core(s)["restarts"] == n)
        assert h.sup.releases.list()[0]["status"] == "watching"
    finally:
        h.sup.shutdown()


@pytest.mark.slow
def test_nothing_is_applied_in_safe_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.integration.test_supervisor import core

    repo = make_repo(tmp_path)
    h = _supervisor(tmp_path, monkeypatch, repo)
    try:
        h.set_mode("crash")
        h.run_until(lambda s: s["safe_mode"]["active"])
        h.set_mode("ok")
        h.run_until(lambda s: core(s)["state"] == "healthy")
        proposal = forge_branch(repo)
        result = h.sup.apply_release(proposal)
        assert result["ok"] is False and "safe mode" in result["error"]
        assert head(repo) == proposal["base_commit"] and h.sup.releases.list() == []
    finally:
        h.sup.shutdown()


def test_a_change_that_isnt_utf8_is_still_read(repo: Path, tmp_path: Path) -> None:
    # Review 2026-10-21: git's output was decoded strictly (and with the ANSI code page on Windows), so one Latin-1
    # byte in a diff crashed the apply. Core and the supervisor both decode as UTF-8 with replacement.
    releases = Releases(repo, tmp_path / "releases.json")
    base = head(repo)
    sh(repo, "checkout", "-q", "-b", "forge/p1")
    (repo / "calc" / "names.py").write_bytes(b"CAFE = 'caf\xe9'\n")
    sh(repo, "add", "-A")
    sh(repo, "commit", "-q", "-m", "latin-1")
    tip = head(repo)
    sh(repo, "checkout", "-q", "main")
    git_diff = ["git", "-C", str(repo), "diff", "--no-color", "--text", f"{base}..{tip}"]
    diff = subprocess.run(git_diff, capture_output=True, check=True).stdout.decode("utf-8", errors="replace")
    proposal = {
        "proposal_id": "p1", "branch": "forge/p1", "base_commit": base, "head_commit": tip,
        "diff_sha": hashlib.sha256(diff.encode()).hexdigest(), "title": "latin-1",
    }  # fmt: skip
    assert releases.apply(**proposal)["status"] == "watching"
