"""Research end to end (Phase 6 "done-when", ADR-0015): a deep report with cited sources lands in the vault,
the save is approval-gated because reading the web taints the task, an injection page can't make the researcher
act, offline blocks a remote fetch, and watchlists detect changes.

The model is the scripted stand-in (tests/support/fake_ollama.py); the web is the fake server
(tests/support/fake_search.py). Needs the Phase 3 protected policy engine (otherwise skipped)."""

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
from tests.support.fake_search import FakeSearch
from universe_core.app import create_app
from universe_core.settings import CoreSettings

DONE = {"done", "failed", "cancelled"}


@pytest.fixture
def search() -> Iterator[FakeSearch]:
    server = FakeSearch().start()
    yield server
    server.stop()


@pytest.fixture
def api(
    make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama, search: FakeSearch
) -> Iterator[Api]:
    settings = make_settings(research_search_endpoint=f"{search.url}/lite/")
    with TestClient(create_app(settings), base_url=BASE) as client:
        a = Api(client, settings, fake_ollama.url)
        a.search = search  # type: ignore[attr-defined]
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
    raise AssertionError(f"task {task_id} is still {task.get('status')}, wanted {statuses}")


def test_deep_research_saves_a_cited_report_after_approval(api: Api) -> None:
    api.search.results = ["alpha", "beta"]  # type: ignore[attr-defined]
    task_id = api.post("/research", {"q": "What is local-first software?", "mode": "deep"}, 202)["task_id"]
    # Reading the web taints the task, so saving the report needs the owner's OK (the backstop).
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    assert approval["tool"] == "vault.save"
    assert "untrusted" in approval["reason"]
    api.post(f"/approvals/{approval['id']}/decision", {"approve": True})

    task = wait_task(api, task_id, DONE)
    assert task["status"] == "done", task.get("error")
    api.drain()  # run the pipeline so the saved note's text is extracted and readable
    note = next(i for i in api.get("/items")["items"] if i["title"] == "Research report")
    text = api.get(f"/items/{note['id']}/text")["text"]
    assert "## Sources" in text and api.search.page_url("alpha") in text  # type: ignore[attr-defined]


def test_an_injection_page_cannot_make_the_researcher_act(api: Api) -> None:
    api.search.results = ["injection"]  # type: ignore[attr-defined]
    task_id = api.post("/research", {"q": "Tell me about this", "mode": "deep"}, 202)["task_id"]
    # Even though the page says "delete the vault / email secrets", the only action offered is the gated save.
    wait_task(api, task_id, {"waiting_approval"})
    [approval] = api.get("/approvals")
    assert approval["tool"] == "vault.save" and "untrusted" in approval["reason"]
    api.post(f"/approvals/{approval['id']}/decision", {"approve": False})  # the owner declines
    wait_task(api, task_id, DONE)

    detail = api.get(f"/tasks/{task_id}")
    used = {s["tool"] for s in detail["steps"] if s["kind"] == "tool_call"}
    assert used <= {"web.search", "web.fetch", "vault.save"}  # no destructive tool was ever called
    assert not [i for i in api.get("/items")["items"] if i["title"] == "Research report"]  # nothing was saved


def test_offline_blocks_a_remote_page_check(api: Api) -> None:
    created = api.post("/watchlists", {"kind": "page", "target": "https://example.com/", "label": "Example"}, 201)
    ctx = api.client.app.state.ctx  # type: ignore[attr-defined]
    ctx.gate.offline = True
    try:
        api.post(f"/watchlists/{created['id']}/check", expect=503)  # blocked before any real request
    finally:
        ctx.gate.offline = False


def test_watchlists_crud_and_change_detection(api: Api) -> None:
    created = api.post("/watchlists", {"kind": "topic", "target": "local-first"}, 201)
    wid = created["id"]
    assert created["enabled"] and [w["id"] for w in api.get("/watchlists")] == [wid]

    api.search.results = ["alpha"]  # type: ignore[attr-defined]
    api.post(f"/watchlists/{wid}/check")  # first check sets the baseline, no hit
    assert api.get(f"/watchlists/{wid}/hits") == []

    api.search.results = ["alpha", "beta"]  # type: ignore[attr-defined] — the topic's results changed
    api.post(f"/watchlists/{wid}/check")
    [hit] = api.get(f"/watchlists/{wid}/hits")
    assert "result" in hit["summary"]

    assert api.client.patch(f"/api/v1/watchlists/{wid}", json={"enabled": False}, headers=AUTH).status_code == 200
    assert not api.get("/watchlists")[0]["enabled"]
    assert api.client.delete(f"/api/v1/watchlists/{wid}", headers=AUTH).status_code == 204
    assert api.get("/watchlists") == []


def test_sent_where_log_lists_outbound_requests(api: Api) -> None:
    ctx = api.client.app.state.ctx  # type: ignore[attr-defined]
    ctx.audit.append(
        actor="agent:researcher",
        action="net.request",
        target_type="host",
        target_id="lite.duckduckgo.com",
        details={"purpose": "research:search", "scheme": "https", "path": "/lite/"},
    )
    entries = api.get("/research/requests")
    assert entries[0]["host"] == "lite.duckduckgo.com" and entries[0]["purpose"] == "research:search"
