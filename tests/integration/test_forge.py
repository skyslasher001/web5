"""Forge end to end on a scratch repository with an injected bug (Phase 5, ADR-0014): a bug report becomes an
issue, Forge reproduces it with a failing test, fixes it in a worktree, verifies and proposes; Core records what
the supervisor did and checks it against git. The Forge agent's YAML is protected core, so the tests load the
proposed one from docs/proposals/phase-5/ (as if the owner had applied the patch)."""

import shutil
import subprocess
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH
from tests.integration.test_vault_api import BASE, Api
from tests.support.fake_ollama import FakeOllama
from tests.support.forge_repo import head, make_repo
from universe_core.app import create_app
from universe_core.forge_tools import load_sentinel
from universe_core.settings import CoreSettings

REPO = Path(__file__).resolve().parents[2]
PROPOSED_AGENTS = REPO / "docs" / "proposals" / "phase-5" / "agents"


def agents_with_forge(tmp: Path) -> Path:
    target = tmp / "agents"
    shutil.copytree(REPO / "agents", target)
    shutil.copytree(PROPOSED_AGENTS, target, dirs_exist_ok=True)
    return target


@pytest.fixture
def forge_api(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama, tmp_path: Path
) -> Iterator[tuple[Api, Path]]:
    repo = make_repo(tmp_path)
    settings = make_settings(repo_dir=repo, agents_dir=agents_with_forge(tmp_path))
    with TestClient(create_app(settings), base_url=BASE) as client:
        api = Api(client, settings, fake_ollama.url)
        yield api, repo
        api.close()


def wait_task(api: Api, task_id: str, timeout: float = 120) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    task: dict[str, Any] = {}
    while time.monotonic() < deadline:
        task = api.get(f"/tasks/{task_id}")["task"]
        if task["status"] in {"done", "failed", "cancelled"}:
            return task
        time.sleep(0.1)
    raise AssertionError(f"task still {task.get('status')}")


def test_forge_says_what_is_installed_and_what_is_missing(client: TestClient) -> None:
    status = client.get("/api/v1/forge/status", headers=AUTH).json()
    # Before the owner applies the Phase 5 protected-core patch, the agent and Sentinel are missing, and say why.
    assert status["agent"] is (REPO / "agents" / "forge.yaml").is_file()
    assert status["agent"] or "protected core" in status["agent_reason"]
    assert status["sentinel"] is (load_sentinel() is not None)
    assert status["sentinel"] or "Sentinel" in status["sentinel_reason"]
    assert status["available"] is False and "UNIVERSE_REPO_DIR" in status["reason"]  # tests set no codebase


def test_a_bug_report_becomes_a_verified_proposal_and_nothing_is_applied(forge_api: tuple[Api, Path]) -> None:
    api, repo = forge_api
    status = api.get("/forge/status")
    assert status["available"] and status["agent"] and status["head"] == head(repo)
    before = head(repo)

    issue = api.post("/forge/reports", {"text": "add(2, 3) returns -1 instead of 5 in the calculator"}, 201)
    assert issue["source"] == "report" and issue["status"] == "open"
    task = api.post(f"/forge/issues/{issue['id']}/fix", None, 202)
    done = wait_task(api, task["task_id"])
    assert done["status"] == "done", done["error"]

    [proposal] = api.get("/forge/proposals")
    assert proposal["status"] == "ready" and proposal["risk"] == "low"
    assert proposal["verification"]["passed"] is True
    repro = proposal["verification"]["repro"]
    assert repro["fails_on_base"] and repro["passes_on_head"]
    assert {f["path"] for f in proposal["files"]} == {"calc/__init__.py", "tests/test_add_regression.py"}
    assert "+    return a + b" in proposal["diff"] and proposal["diff_sha"]
    assert "subtracted" in proposal["root_cause"]
    assert proposal["reviews"]["critic"]["output"]  # Critic reviewed the diff
    sentinel = proposal["reviews"]["sentinel"]
    if load_sentinel() is None:  # protected core: not installed until the owner applies the Phase 5 patch
        assert sentinel["available"] is False
    else:
        assert sentinel["verdict"] == "pass" and sentinel["risk"] == "low" and sentinel["findings"] == []
    assert not proposal["touches_protected"]
    assert api.get("/forge/issues")[0]["status"] == "proposed"

    # Forge applied nothing: the owner's checkout is exactly as it was.
    assert head(repo) == before
    assert "return a - b" in (repo / "calc" / "__init__.py").read_text()
    events = [e["type"] for e in api.get("/events", params={"tail": 200})["events"]]
    assert "forge.proposal.created" in events

    # Core believes "applied" only when git agrees.
    claim = api.client.post(
        f"/api/v1/forge/proposals/{proposal['id']}/release", json={"event": "applied", "release": "r1"}, headers=AUTH
    )
    assert claim.status_code == 409
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "--ff-only", proposal["branch"]], check=True)
    applied = api.post(f"/forge/proposals/{proposal['id']}/release", {"event": "applied", "release": "r1"})
    assert applied["status"] == "applied" and applied["release"] == "r1"
    # Idempotent: Electron main re-syncs the same applied release after a Core restart (regression).
    resynced = api.post(f"/forge/proposals/{proposal['id']}/release", {"event": "applied", "release": "r1"})
    assert resynced["status"] == "applied" and resynced["release"] == "r1"
    assert api.get("/forge/issues", params={"status_filter": "fixed"})[0]["id"] == issue["id"]
    rolled = api.post(f"/forge/proposals/{proposal['id']}/release", {"event": "rolled_back", "release": "r1"})
    assert rolled["status"] == "rolled_back"
    assert api.get("/forge/issues")[0]["status"] == "open"


def test_rejecting_a_proposal_discards_its_worktree_and_reopens_the_issue(forge_api: tuple[Api, Path]) -> None:
    api, _repo = forge_api
    issue = api.post("/forge/reports", {"text": "add(1, 1) returns 0 instead of 2"}, 201)
    task = api.post(f"/forge/issues/{issue['id']}/fix", None, 202)
    assert wait_task(api, task["task_id"])["status"] == "done"
    [proposal] = api.get("/forge/proposals")
    rejected = api.post(f"/forge/proposals/{proposal['id']}/reject")
    assert rejected["status"] == "rejected"
    assert api.get("/forge/issues")[0]["status"] == "open"
    worktree = api.client.app.state.ctx.forge.root / "worktrees" / proposal["id"]  # type: ignore[attr-defined]
    assert not worktree.exists()
    assert api.client.post(f"/api/v1/forge/proposals/{proposal['id']}/reject", headers=AUTH).status_code == 409
    # A rejected proposal can't be recorded as applied (regression: the guard blocks rejected -> applied).
    stolen = api.client.post(
        f"/api/v1/forge/proposals/{proposal['id']}/release", json={"event": "applied", "release": "r9"}, headers=AUTH
    )
    assert stolen.status_code == 409


def test_a_report_forge_cant_reproduce_changes_nothing(forge_api: tuple[Api, Path]) -> None:
    api, repo = forge_api
    issue = api.post("/forge/reports", {"text": "Something feels slow sometimes"}, 201)
    task = api.post(f"/forge/issues/{issue['id']}/fix", None, 202)
    done = wait_task(api, task["task_id"])
    assert done["status"] == "done" and "didn't change anything" in done["output"]
    assert api.get("/forge/proposals") == []
    assert not (api.client.app.state.ctx.forge.root / "worktrees").exists() or not any(  # type: ignore[attr-defined]
        (api.client.app.state.ctx.forge.root / "worktrees").iterdir()  # type: ignore[attr-defined]
    )
    assert head(repo)


def test_a_proposal_being_verified_cannot_be_rejected(forge_api: tuple[Api, Path]) -> None:
    """Review 2026-10-21: rejecting mid-verification removed the worktree, then the verify thread set the
    proposal back to 'draft' — a rejected proposal came back with no worktree."""
    api, _repo = forge_api
    issue = api.post("/forge/reports", {"text": "add(1, 1) returns 0 instead of 2"}, 201)
    task = api.post(f"/forge/issues/{issue['id']}/fix", None, 202)
    assert wait_task(api, task["task_id"])["status"] == "done"
    [proposal] = api.get("/forge/proposals")
    forge = api.client.app.state.ctx.forge  # type: ignore[attr-defined]
    forge.update(proposal["id"], status="verifying")  # as while forge.check runs
    refused = api.client.post(f"/api/v1/forge/proposals/{proposal['id']}/reject", headers=AUTH)
    assert refused.status_code == 409 and "being verified" in refused.text
    assert (forge.root / "worktrees" / proposal["id"]).exists()  # the checks still have their worktree
