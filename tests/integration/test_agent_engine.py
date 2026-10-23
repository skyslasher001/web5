"""The agent engine end to end (Phase 3 "done when"): Core delegates to the librarian, the librarian searches
and reads, Core links the notes to a galaxy after you approve, Critic reviews, and every step is audited.

The model is the scripted stand-in in tests/support/fake_ollama.py. These tests need the protected policy
engine (docs/proposals/phase-3-protected-core.md); without it they're skipped with that reason.
"""

import json
import sys
import time
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

pytest.importorskip(
    "universe_core.protected.policy", reason="needs the Phase 3 protected-core patch (policy engine) to be applied"
)

from tests.conftest import AUTH
from tests.integration.test_vault_api import BASE, Api
from tests.support.fake_ollama import FakeOllama
from universe_core.app import create_app
from universe_core.settings import CoreSettings

DONE = {"done", "failed", "cancelled"}


@pytest.fixture
def api(make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama) -> Iterator[Api]:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as client:
        a = Api(client, settings, fake_ollama.url)
        yield a
        a.close()


def wait_task(api: Api, task_id: str, statuses: set[str], timeout: float = 30) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    task: dict[str, Any] = {}
    while time.monotonic() < deadline:
        task = api.get(f"/tasks/{task_id}")["task"]
        if task["status"] in statuses:
            return task
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} is still {task['status']}, wanted {statuses}")


def seed_notes(api: Api) -> None:
    for title, text in [
        ("Austin land deal", "The Austin land deal closes in November. The seller wants 40k for the parcel."),
        ("Lake parcel land deal", "A land deal by the lake: the owner is motivated and open to terms."),
        ("Groceries", "Eggs, flour and sugar for the weekend."),
    ]:
        api.post("/capture", {"text": text, "title": title}, 201)
    api.drain()


def project_id(api: Api, name: str) -> str:
    return next(p["id"] for p in api.get("/projects") if p["name"] == name)


def test_find_summarize_and_link_with_a_full_audit_trail(api: Api) -> None:
    seed_notes(api)
    devmind = project_id(api, "DevMind")
    status = api.get("/engine")
    assert status["available"] and "agent.delegate" in status["tools"]

    run = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
        202,
    )
    task_id = run["task_id"]
    # Reading notes tainted the task, so linking them waits for you.
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    assert approval["tool"] == "project.add_items" and approval["risk"] == "medium"
    assert approval["summary"] == "Add 2 item(s) to the galaxy 'DevMind'"
    assert "untrusted" in approval["reason"]
    api.post(f"/approvals/{approval['id']}/decision", {"approve": True})

    task = wait_task(api, task_id, DONE)
    assert task["status"] == "done", task["error"]
    assert task["output"].startswith("Summary: ")
    assert "The Austin land deal closes in November." in task["output"]
    assert "A land deal by the lake: the owner is motivated and open to terms." in task["output"]
    assert "Added 2 item(s) to DevMind." in task["output"]
    assert task["output"].endswith("— Checked by Critic.")
    assert task["tainted"]

    linked = {i["title"] for i in api.get("/items", params={"project": devmind})["items"]}
    assert linked == {"Austin land deal", "Lake parcel land deal"}

    detail = api.get(f"/tasks/{task_id}")
    kinds = [s["kind"] for s in detail["steps"]]
    assert "delegate" in kinds and "review" in kinds
    assert [
        s["decision"] for s in detail["steps"] if s["tool"] == "project.add_items" and s["kind"] == "tool_call"
    ] == ["ask"]
    children = {c["agent_id"]: c for c in detail["children"]}
    assert children["librarian"]["status"] == "done" and children["critic"]["status"] == "done"
    librarian = api.get(f"/tasks/{children['librarian']['id']}")
    tools_used = [s["tool"] for s in librarian["steps"] if s["kind"] == "tool_call"]
    assert tools_used == ["vault.search", "vault.read", "vault.read"]

    audit = api.get("/audit", params={"limit": 500})
    actions = [e["action"] for e in audit]
    for action in ("task.started", "tool.call", "approval.decided", "item.linked", "task.finished"):
        assert action in actions, action
    calls = [e["details"] for e in audit if e["action"] == "tool.call"]
    assert {"tool": "project.add_items", "decision": "approved_by_user"}.items() <= next(
        c for c in calls if c["tool"] == "project.add_items"
    ).items()
    assert api.get("/audit/verify")["ok"]
    # The audit log keeps ids and hashes, never the content of your notes.
    assert "Austin" not in json.dumps(audit) and "40k" not in json.dumps(audit)
    usage = api.get("/budget")
    assert usage["calls"] >= 5 and usage["spent_usd"] == 0


def test_declining_the_approval_changes_nothing(api: Api) -> None:
    seed_notes(api)
    task_id = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
        202,
    )["task_id"]
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    api.post(f"/approvals/{approval['id']}/decision", {"approve": False})
    task = wait_task(api, task_id, DONE)
    assert task["status"] == "done"
    assert "The user declined this action" in task["output"] or "declined" in task["output"]
    assert api.get("/items", params={"project": project_id(api, "DevMind")})["items"] == []
    denied = [e for e in api.get("/audit", params={"limit": 500}) if e["action"] == "tool.call"]
    assert any(e["details"]["decision"] == "denied_by_user" and e["outcome"] == "denied" for e in denied)


def test_approving_by_voice_is_recorded_and_limited(api: Api) -> None:
    """Phase 7: you can say "approve", but not for high-risk actions or to set a standing rule."""
    seed_notes(api)
    task_id = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
        202,
    )["task_id"]
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    assert approval["risk"] == "medium"
    rule = api.client.post(
        f"/api/v1/approvals/{approval['id']}/decision",
        json={"approve": True, "remember": True, "via": "voice"},
        headers=AUTH,
    )
    assert rule.status_code == 409 and api.get("/permissions/rules") == []
    decided = api.post(f"/approvals/{approval['id']}/decision", {"approve": True, "via": "voice"})
    assert decided["status"] == "approved" and decided["decided_via"] == "voice"
    assert wait_task(api, task_id, DONE)["status"] == "done"


def test_high_risk_actions_cannot_be_approved_by_voice(api: Api) -> None:
    conn = api.client.app.state.ctx.dbs.universe  # type: ignore[attr-defined]
    seed_notes(api)
    task_id = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
        202,
    )["task_id"]
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    conn.execute("UPDATE approvals SET risk = 'high' WHERE id = ?", (approval["id"],))  # as a high-risk tool would
    refused = api.client.post(
        f"/api/v1/approvals/{approval['id']}/decision", json={"approve": True, "via": "voice"}, headers=AUTH
    )
    assert refused.status_code == 409 and "need a click" in refused.text
    assert api.get("/approvals")[0]["status"] == "pending"
    # Declining by voice is always fine: it can only stop something.
    denied = api.post(f"/approvals/{approval['id']}/decision", {"approve": False, "via": "voice"})
    assert denied["status"] == "denied" and denied["decided_via"] == "voice"


def test_a_rule_you_set_skips_the_question_but_taint_still_asks(api: Api) -> None:
    seed_notes(api)
    rule = api.post("/permissions/rules", {"agent_id": "core", "tool": "project.add_items", "decision": "allow"}, 201)
    task_id = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
        202,
    )["task_id"]
    # Allowed by rule, but the task read your files: without applies_when_tainted it still asks.
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    api.post(f"/approvals/{approval['id']}/decision", {"approve": True})
    wait_task(api, task_id, DONE)

    api.client.delete(f"/api/v1/permissions/rules/{rule['id']}", headers=AUTH)
    api.post(
        "/permissions/rules",
        {"agent_id": "core", "tool": "project.add_items", "decision": "allow", "applies_when_tainted": True},
        201,
    )
    second = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project Ember Wolf."},
        202,
    )["task_id"]
    task = wait_task(api, second, DONE)
    assert task["status"] == "done" and "Added 2 item(s) to Ember Wolf Acquisitions." in task["output"]
    assert api.get("/approvals") == []
    rules = api.get("/permissions/rules")
    assert [r["applies_when_tainted"] for r in rules] == [True]
    assert any(e["action"] == "permission.changed" for e in api.get("/audit", params={"limit": 500}))


def test_the_kill_switch_stops_everything(api: Api) -> None:
    seed_notes(api)
    task_id = api.post(
        "/agents/core/run",
        {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
        202,
    )["task_id"]
    wait_task(api, task_id, {"waiting_approval"})
    engaged = api.post("/killswitch", {"engaged": True})
    assert engaged["engaged"] and engaged["via"] == "hud"
    task = wait_task(api, task_id, DONE)
    assert task["status"] in {"cancelled", "done"}
    assert api.get("/approvals") == []  # the pending approval was refused
    assert api.client.app.state.ctx.gate.killed  # type: ignore[attr-defined]

    blocked = api.post("/agents/librarian/run", {"instruction": "Find my notes about land deal."}, 202)["task_id"]
    task = wait_task(api, blocked, DONE)
    assert task["status"] == "failed" and "kill switch" in (task["error"] or "")
    # Releasing is not something Core's API (or anything in Core) can do.
    response = api.client.post("/api/v1/killswitch", json={"engaged": False}, headers=AUTH)
    assert response.status_code == 403
    assert any(e["action"] == "killswitch" for e in api.get("/audit", params={"limit": 500}))


def test_guardrails_stop_loops_and_bad_tool_calls(api: Api) -> None:
    loop = api.post("/agents/navigator/run", {"instruction": "[[loop]] find it"}, 202)["task_id"]
    task = wait_task(api, loop, DONE)
    assert task["status"] == "failed" and "Stopped a loop" in task["error"]

    unknown = api.post("/agents/navigator/run", {"instruction": "[[unknown-tool]] please"}, 202)["task_id"]
    task = wait_task(api, unknown, DONE)
    steps = api.get(f"/tasks/{unknown}")["steps"]
    assert any(s["decision"] == "unknown" and s["tool"] == "files__delete_everything" for s in steps)
    assert task["status"] == "done"

    bad = api.post("/agents/navigator/run", {"instruction": "[[bad-args]] please"}, 202)["task_id"]
    wait_task(api, bad, DONE)
    assert any(s["decision"] == "invalid" for s in api.get(f"/tasks/{bad}")["steps"])


def test_memories_about_you_wait_for_your_ok(api: Api) -> None:
    task_id = api.post("/agents/core/run", {"instruction": "[[remember]] I prefer short summaries"}, 202)["task_id"]
    wait_task(api, task_id, DONE)
    [proposed] = api.get("/memories", params={"status": "proposed"})
    assert proposed["scope"] == "self" and proposed["content"] == "I prefer short summaries"
    approved = api.post(f"/memories/{proposed['id']}/decision", {"approve": True})
    assert approved["status"] == "active"
    # Approved memories reach the agent's context next time (as notes, not instructions).
    api.post("/agents/core/run", {"instruction": "How should you write summaries for me?"}, 202)
    time.sleep(0.5)
    request = api.client.app.state.ctx  # type: ignore[attr-defined]
    assert request.memory.search("summaries", ["self"])[0].last_used_at is not None


def test_chat_runs_through_the_engine(api: Api) -> None:
    seed_notes(api)
    sent = api.post("/chat", {"text": "Find my notes about land deal and summarize them."}, 202)
    deadline = time.monotonic() + 30
    messages: list[dict[str, Any]] = []
    while time.monotonic() < deadline:
        messages = api.get(f"/conversations/{sent['conversation_id']}/messages")
        if len(messages) == 2:
            break
        time.sleep(0.05)
    assert messages[-1]["role"] == "assistant"
    # Core answered with tools: the reply links to its task and trace.
    task = api.get("/tasks", params={"agent": "core"})[0]
    assert task["conversation_id"] == sent["conversation_id"]
    assert messages[-1]["task_id"] == task["id"]


def test_taint_carries_over_to_later_turns_of_the_same_chat(api: Api) -> None:
    """Regression: each chat turn started a new task untainted, but the conversation history it is given holds
    the earlier turn's answer built from untrusted text (your notes), so injected instructions could steer a
    later turn's tool calls without the taint rules applying."""
    seed_notes(api)

    def chat_task(conversation_id: str, replies: int) -> dict[str, Any]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            messages = api.get(f"/conversations/{conversation_id}/messages")
            if len(messages) >= 2 * replies and messages[-1]["task_id"]:
                return wait_task(api, messages[-1]["task_id"], DONE)
            time.sleep(0.05)
        raise AssertionError(f"no reply {replies} in conversation {conversation_id}")

    text = "Find my notes about land deal and summarize them."
    sent = api.post("/chat", {"text": text, "agent_id": "librarian"}, 202)
    conversation_id = sent["conversation_id"]
    first = chat_task(conversation_id, 1)
    assert first["tainted"]  # it read your notes

    follow_up = {"text": "Thanks. Anything else?", "conversation_id": conversation_id, "agent_id": "librarian"}
    api.post("/chat", follow_up, 202)
    later = chat_task(conversation_id, 2)
    assert later["id"] != first["id"] and later["conversation_id"] == conversation_id
    assert later["tainted"]

    other = api.post("/chat", {"text": "Hello there", "agent_id": "librarian"}, 202)  # a new conversation starts clean
    assert not chat_task(other["conversation_id"], 1)["tainted"]


def test_mcp_tools_ask_first_and_their_output_is_untrusted(api: Api) -> None:
    server = str(__import__("pathlib").Path(__file__).resolve().parents[1] / "support" / "mcp_demo_server.py")
    api.post("/mcp/servers", {"name": "demo", "command": sys.executable, "args": [server]}, 201)
    task_id = api.post("/agents/core/run", {"instruction": "[[mcp]] add 2 and 3"}, 202)["task_id"]
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    assert approval["tool"] == "mcp.demo.add" and "MCP server" in approval["reason"]
    assert approval["summary"].startswith("Run add on the MCP server demo")
    api.post(f"/approvals/{approval['id']}/decision", {"approve": True})
    task = wait_task(api, task_id, DONE)
    assert task["status"] == "done" and task["output"].startswith("The MCP server says")
    assert "5" in task["output"] and task["tainted"]
