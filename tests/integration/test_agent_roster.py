"""The Agents tab: every agent with a synopsis and stats; add your own, turn agents off and on, remove yours.
Real Core with the scripted fake model; temporary data and vault directories."""

import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from tests.conftest import AUTH
from tests.integration.test_vault_api import BASE, Api
from tests.support.fake_ollama import FakeOllama
from universe_agents.registry import load_agents
from universe_core.agent_engine import specialists_block
from universe_core.app import create_app
from universe_core.settings import CoreSettings

REPO_AGENTS = Path(__file__).resolve().parents[2] / "agents"

RESEARCHER = {
    "name": "Deal Scout",
    "purpose": "Finds land-deal notes and lists the open questions in them.",
    "synopsis": "Reads your land-deal notes and tells you what's still unanswered.",
    "instructions": "You read the owner's land-deal notes and list the open questions, citing each note.",
    "color": "rose",
    "tools": ["vault.search", "vault.read"],
    "permission_tier": "read",
}


def roster(api: Api) -> dict[str, dict[str, Any]]:
    return {a["id"]: a for a in api.get("/agents/roster")}


def wait_done(api: Api, task_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        task = api.get(f"/tasks/{task_id}")["task"]
        if task["status"] in {"done", "failed", "cancelled"}:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} didn't finish")


def test_every_agent_has_a_synopsis_and_stats(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama
) -> None:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as client:
        api = Api(client, settings, fake_ollama.url)
        try:
            agents = roster(api)
            assert {"core", "librarian", "scribe", "navigator", "critic"} <= set(agents)
            for agent in agents.values():
                assert agent["origin"] == "built-in" and agent["enabled"] and len(agent["synopsis"]) > 40
            assert agents["core"]["locked_reason"] and agents["critic"]["locked_reason"]
            assert agents["librarian"]["locked_reason"] is None
            assert agents["librarian"]["stats"] == {
                "tasks": 0, "done": 0, "failed": 0, "cancelled": 0, "success_rate": None,
                "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0, "avg_steps": None, "last_active": None,
            }  # fmt: skip

            task = api.post("/agents/navigator/run", {"instruction": "Say hello."}, 202)
            assert wait_done(api, task["task_id"])["status"] == "done"
            stats = roster(api)["navigator"]["stats"]
            assert stats["tasks"] == 1 and stats["done"] == 1 and stats["success_rate"] == 1.0
            assert stats["last_active"] is not None
        finally:
            api.close()


def test_add_run_turn_off_and_remove_your_own_agent(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama
) -> None:
    settings = make_settings()
    repo_yaml = {p.name: p.read_text(encoding="utf-8") for p in REPO_AGENTS.glob("*.yaml")}
    with TestClient(create_app(settings), base_url=BASE) as client:
        api = Api(client, settings, fake_ollama.url)
        try:
            made = api.post("/agents", RESEARCHER, 201)
            assert made["id"] == "deal-scout" and made["origin"] == "custom" and made["enabled"]
            assert (settings.data_dir / "agents" / "deal-scout.yaml").is_file()
            assert "deal-scout" in {a["id"] for a in api.get("/agents")}  # in the dock too
            # Core can delegate to it: the live specialists list includes it.
            app_ctx = client.app.state.ctx  # type: ignore[attr-defined]
            assert "deal-scout: Finds land-deal notes" in specialists_block(app_ctx.engine.agents, "core")

            task = api.post("/agents/deal-scout/run", {"instruction": "Any open questions?"}, 202)
            assert wait_done(api, task["task_id"])["status"] == "done"
            assert roster(api)["deal-scout"]["stats"]["tasks"] == 1

            # Not allowed: unknown tools, delegation, system access, a name that's taken.
            assert (
                "nope.tool"
                in api.post("/agents", {**RESEARCHER, "name": "Other", "tools": ["nope.tool"]}, 422)["detail"]
            )
            api.post("/agents", {**RESEARCHER, "name": "Boss", "tools": ["agent.delegate"]}, 422)
            api.post("/agents", {**RESEARCHER, "name": "Root", "permission_tier": "system"}, 422)
            api.post("/agents", {**RESEARCHER, "name": "Librarian"}, 422)

            # Turn a built-in off and on; Core and Critic can't be turned off.
            off = client.patch("/api/v1/agents/librarian", json={"enabled": False}, headers=AUTH)
            assert off.status_code == 200 and off.json()["enabled"] is False
            assert "librarian" not in {a["id"] for a in api.get("/agents")}
            assert "librarian" not in app_ctx.engine.agents
            assert client.patch("/api/v1/agents/core", json={"enabled": False}, headers=AUTH).status_code == 409
            assert client.patch("/api/v1/agents/critic", json={"enabled": False}, headers=AUTH).status_code == 409

            # Synopses: a built-in's edit lives in settings (the shipped YAML stays); yours is in its file.
            edited = client.patch("/api/v1/agents/scribe", json={"synopsis": "Writes my notes."}, headers=AUTH)
            assert edited.json()["synopsis"] == "Writes my notes."
            client.patch("/api/v1/agents/deal-scout", json={"synopsis": "Land questions."}, headers=AUTH)
            assert "Land questions." in (settings.data_dir / "agents" / "deal-scout.yaml").read_text(encoding="utf-8")
        finally:
            api.close()

    # Everything survives a restart.
    with TestClient(create_app(settings), base_url=BASE) as client:
        api = Api(client, settings, fake_ollama.url)
        try:
            agents = roster(api)
            assert agents["deal-scout"]["synopsis"] == "Land questions."
            assert agents["scribe"]["synopsis"] == "Writes my notes."
            assert agents["librarian"]["enabled"] is False
            assert client.patch("/api/v1/agents/librarian", json={"enabled": True}, headers=AUTH).json()["enabled"]

            # Remove yours (its files are kept aside, not deleted); built-ins can only be turned off.
            assert client.delete("/api/v1/agents/deal-scout", headers=AUTH).status_code == 204
            assert "deal-scout" not in roster(api)
            kept = list((settings.data_dir / "agents" / ".removed").glob("deal-scout-*/deal-scout.yaml"))
            assert len(kept) == 1
            assert client.delete("/api/v1/agents/scribe", headers=AUTH).status_code == 409
            assert client.delete("/api/v1/agents/nobody", headers=AUTH).status_code == 404
            events = [e["type"] for e in api.get("/events", params={"tail": 200})["events"]]
            assert {"agent.updated", "agent.removed"} <= set(events)
        finally:
            api.close()
    # The app never edits the shipped agent files.
    assert {p.name: p.read_text(encoding="utf-8") for p in REPO_AGENTS.glob("*.yaml")} == repo_yaml
    assert set(load_agents(REPO_AGENTS)) >= {"core", "critic", "librarian", "navigator", "scribe"}
