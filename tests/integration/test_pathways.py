"""Neural pathways (SPEC §10, owner-approved 2026-10-14): items that fire together are recorded for the brain
layer, and each firing is a `link.fired` event the universe shows as a signal pulse."""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH
from tests.integration.test_agent_engine import DONE, project_id, seed_notes, wait_task
from tests.integration.test_vault_api import BASE, Api
from tests.support.fake_ollama import FakeOllama
from universe_core.app import create_app
from universe_core.settings import CoreSettings


@pytest.fixture
def api(make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama) -> Iterator[Api]:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as client:
        a = Api(client, settings, fake_ollama.url)
        yield a
        a.close()


def fired_events(api: Api, sub: Any) -> list[dict[str, Any]]:
    out = []
    while not sub.queue.empty():
        out.append(sub.queue.get_nowait().payload)
    return out


def activity(api: Api) -> list[tuple[str, str, str]]:
    rows = api._ctx.conn.execute("SELECT a_id, b_id, source FROM link_activity ORDER BY at").fetchall()
    return [(r["a_id"], r["b_id"], r["source"]) for r in rows]


def test_opening_one_item_right_after_another_fires_the_pathway(api: Api) -> None:
    a = api.post("/capture", {"text": "See [[Bee]].", "title": "Ay"}, 201)["item_id"]
    b = api.post("/capture", {"text": "The bee note.", "title": "Bee"}, 201)["item_id"]
    c = api.post("/capture", {"text": "Unrelated.", "title": "Sea"}, 201)["item_id"]
    api.drain()
    ctx = api.client.app.state.ctx  # type: ignore[attr-defined]
    sub = ctx.bus.subscribe(["link.fired"])
    try:
        api.post(f"/items/{a}/open")
        api.post(f"/items/{a}/open")  # the same item again: nothing fires
        assert activity(api) == []
        api.post(f"/items/{b}/open")
        assert activity(api) == [(*sorted((a, b)), "sequence")]
        [event] = fired_events(api, sub)
        link = api.get(f"/items/{a}/links")["outgoing"][0]["id"]
        assert event == {"from_id": a, "to_id": b, "source": "sequence", "link_id": link}  # it travels the link

        # Unlinked items fire too (that's how the brain layer will suggest links); long gaps don't.
        api.post(f"/items/{c}/open")
        assert fired_events(api, sub)[0]["link_id"] is None
        with api._ctx.conn:
            api._ctx.conn.execute("UPDATE items SET last_opened_at = '2020-01-01T00:00:00.000Z'")
        api.post(f"/items/{a}/open")
        assert len(activity(api)) == 2 and fired_events(api, sub) == []
        # Trashed items never fire.
        assert api.client.delete(f"/api/v1/items/{c}", headers=AUTH).status_code == 200
        api.post(f"/items/{b}/open")
        assert len(activity(api)) == 3
    finally:
        ctx.bus.unsubscribe(sub)


def test_an_agent_moving_between_items_fires_the_pathways_it_travels(api: Api) -> None:
    seed_notes(api)
    project_id(api, "DevMind")
    ctx = api.client.app.state.ctx  # type: ignore[attr-defined]
    sub = ctx.bus.subscribe(["link.fired"])
    try:
        run = api.post(
            "/agents/core/run",
            {"instruction": "Find my notes about land deal, summarize them, and link them to project DevMind."},
            202,
        )
        wait_task(api, run["task_id"], {"waiting_approval"})
        [approval] = api.get("/approvals")
        api.post(f"/approvals/{approval['id']}/decision", {"approve": True})
        assert wait_task(api, run["task_id"], DONE)["status"] == "done"
        agent_rows = [r for r in activity(api) if r[2] == "agent"]
        assert agent_rows, "the Librarian read two notes one after the other"
        events = fired_events(api, sub)
        assert any(e["source"] == "agent" and e.get("agent_id") for e in events)
    finally:
        ctx.bus.unsubscribe(sub)
