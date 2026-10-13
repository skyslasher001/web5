"""The universe view's REST (Phase 4, ADR-0012): scene data as columns, links and backlinks, note editing,
the cached Semantic layout and similar items. Real Core, real workers drained in-process, fake Ollama.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient

from tests.conftest import AUTH
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


def capture(api: Api, text: str, title: str | None = None) -> str:
    body: dict[str, str] = {"text": text}
    if title:
        body["title"] = title
    return api.post("/capture", body, 201)["item_id"]


def test_scene_data_pages_as_columns_and_reports_changes(api: Api) -> None:
    ids = [capture(api, f"Harbor note {n}") for n in range(5)]
    api.drain()
    devmind = next(p["id"] for p in api.get("/projects") if p["name"] == "DevMind")
    api.client.patch(f"/api/v1/items/{ids[0]}", json={"add_projects": [devmind]}, headers=AUTH)

    first = api.get("/universe/items", params={"limit": 3})
    assert first["total"] == 5 and len(first["ids"]) == 3 and first["next_cursor"]
    rest = api.get("/universe/items", params={"limit": 3, "cursor": first["next_cursor"]})
    assert rest["next_cursor"] is None
    every = first["ids"] + rest["ids"]
    assert sorted(every) == sorted(ids)
    columns = ("types", "titles", "galaxies", "created", "captured", "opened", "opens", "statuses", "pinned")
    for page in (first, rest):
        assert all(len(page[c]) == len(page["ids"]) for c in columns)
    galaxies = dict(zip(every, first["galaxies"] + rest["galaxies"], strict=True))
    assert galaxies[ids[0]] == devmind and galaxies[ids[1]] is None
    assert all(t == "note" for t in first["types"]) and min(first["created"]) > 1_700_000_000

    # Only what changed since then: an opened item comes back, a trashed one is listed as removed.
    since = rest["server_time"]
    api.post(f"/items/{ids[1]}/open", expect=200)
    api.client.delete(f"/api/v1/items/{ids[2]}", headers=AUTH)
    changed = api.get("/universe/items", params={"since": since})
    assert changed["removed"] == [ids[2]]
    assert ids[1] in changed["ids"] and changed["opens"][changed["ids"].index(ids[1])] == 1
    assert changed["total"] == 4
    assert api.client.get("/api/v1/universe/items?cursor=abc", headers=AUTH).status_code == 400


def test_wikilinks_resolve_late_and_give_backlinks(api: Api) -> None:
    plan = capture(api, "# Land plan\n\nSee [[Seller call]] and [[Parcel map|the map]] and [[Seller call#notes]].")
    api.drain()
    pending = api.get(f"/items/{plan}/links")
    assert pending["outgoing"] == [] and sorted(pending["unresolved"]) == ["Parcel map", "Seller call"]

    call = capture(api, "The seller wants 40k.", title="Seller call")
    api.drain()
    links = api.get(f"/items/{plan}/links")
    assert [link["item"]["id"] for link in links["outgoing"]] == [call]
    assert links["outgoing"][0]["kind"] == "wikilink" and links["unresolved"] == ["Parcel map"]
    back = api.get(f"/items/{call}/links")
    assert [link["item"]["id"] for link in back["incoming"]] == [plan]

    scene = api.get("/universe/links")
    assert list(zip(scene["sources"], scene["targets"], strict=True)) == [(plan, call)]

    # A link you make by hand can be removed; one that comes from the note's text can't (edit the note).
    other = capture(api, "Groceries")
    made = api.post("/links", {"from_id": call, "to_id": other}, 201)
    assert len(api.get("/universe/links")["ids"]) == 2
    assert api.client.delete(f"/api/v1/links/{made['id']}", headers=AUTH).status_code == 204
    wiki = links["outgoing"][0]["id"]
    assert api.client.delete(f"/api/v1/links/{wiki}", headers=AUTH).status_code == 409
    assert api.post("/links", {"from_id": call, "to_id": call}, 422)
    assert api.post("/links", {"from_id": call, "to_id": "nope"}, 404)
    # A trashed item's links disappear from the universe.
    api.client.delete(f"/api/v1/items/{call}", headers=AUTH)
    assert api.get("/universe/links")["ids"] == []


def test_editing_a_note_keeps_versions_and_refuses_stale_saves(api: Api) -> None:
    note = capture(api, "First draft about the lake.", title="Lake")
    api.drain()
    content = api.get(f"/items/{note}/content")
    assert content["body"].strip() == "First draft about the lake." and content["version"] == 1

    saved = api.client.put(
        f"/api/v1/items/{note}/content",
        json={"body": "Second draft. Links to [[Lake]] are ignored.", "base_version": 1},
        headers=AUTH,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["version"] == 2 and saved.json()["body"].startswith("Second draft.")
    # The frontmatter stayed, so the item keeps its identity.
    path = api.vault.abs(api.get(f"/items/{note}")["path"])
    assert path.read_text(encoding="utf-8").startswith("---\n") and f"id: {note}" in path.read_text(encoding="utf-8")
    assert [v["n"] for v in api.get(f"/items/{note}")["versions"]] == [1, 2]

    stale = api.client.put(
        f"/api/v1/items/{note}/content", json={"body": "Overwrite!", "base_version": 1}, headers=AUTH
    )
    assert stale.status_code == 409
    api.drain()
    assert "Second draft" in api.get(f"/items/{note}/text")["text"]
    assert api.get(f"/items/{note}/links")["outgoing"] == []  # a note can't link to itself


def test_semantic_layout_is_computed_by_a_worker_and_cached(api: Api) -> None:
    for text in ["my dog", "the puppy", "a kitten", "a sedan car", "the truck", "an automobile"]:
        capture(api, text)
    api.drain()  # embeds them
    first = api.get("/layout/semantic")
    assert first["status"] == "computing" and first["model"] == "fake-embed:latest"
    api.drain()  # the layout job
    ready = api.get("/layout/semantic")
    assert ready["status"] == "ready" and not ready["stale"]
    assert len(ready["ids"]) == 6 and len(ready["positions"]) == 18
    events = api.get("/events", params={"tail": 50})["events"]
    assert any(e["type"] == "layout.updated" for e in events)


def test_similar_items_come_from_vectors(api: Api) -> None:
    dog = capture(api, "my dog at the park")
    puppy = capture(api, "a puppy in the park")
    capture(api, "an invoice for the car repair")
    api.drain()
    similar = api.get(f"/items/{dog}/similar", params={"limit": 2})
    assert similar[0]["id"] == puppy and dog not in [s["id"] for s in similar]


def test_galaxy_goals_and_status_from_the_dashboard(api: Api) -> None:
    devmind = next(p for p in api.get("/projects") if p["name"] == "DevMind")
    assert devmind["goals"] == []
    response = api.client.patch(
        f"/api/v1/projects/{devmind['id']}",
        json={"status": "paused", "goals": [{"text": "Ship the editor"}, {"text": "Write docs", "done": True}]},
        headers=AUTH,
    )
    assert response.status_code == 200, response.text
    updated = response.json()
    assert updated["status"] == "paused"
    assert updated["goals"] == [{"text": "Ship the editor", "done": False}, {"text": "Write docs", "done": True}]
    assert next(p for p in api.get("/projects") if p["id"] == devmind["id"])["goals"][1]["done"] is True
    assert any(e["type"] == "project.updated" for e in api.get("/events", params={"tail": 20})["events"])
    assert api.client.patch("/api/v1/projects/nope", json={"status": "done"}, headers=AUTH).status_code == 404
    bad = api.client.patch(f"/api/v1/projects/{devmind['id']}", json={"status": "gone"}, headers=AUTH)
    assert bad.status_code == 422
