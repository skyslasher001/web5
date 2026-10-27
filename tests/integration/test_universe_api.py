"""The universe view's REST (Phase 4, ADR-0012): scene data as columns, links and backlinks, note editing,
the cached Semantic layout and similar items. Real Core, real workers drained in-process, fake Ollama.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import pytest
from fastapi import FastAPI
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


def test_a_wikilink_outlives_its_target_and_finds_the_next_one(api: Api) -> None:
    """Regression: a resolved [[link]] cascaded away with its target, so it vanished from the note's links and
    never resolved again; and a pending link written as a slug never resolved."""
    plan = capture(api, "See [[Foo]] and [[bar-baz]].", title="Plan")
    foo = capture(api, "First foo.", title="Foo")
    api.drain()
    assert [link["item"]["id"] for link in api.get(f"/items/{plan}/links")["outgoing"]] == [foo]

    # Trashed: the link waits for its target again; restored: it points back.
    api.client.delete(f"/api/v1/items/{foo}", headers=AUTH)
    assert sorted(api.get(f"/items/{plan}/links")["unresolved"]) == ["Foo", "bar-baz"]
    assert api.client.post(f"/api/v1/items/{foo}/restore", headers=AUTH).status_code == 200
    links = api.get(f"/items/{plan}/links")
    assert [link["item"]["id"] for link in links["outgoing"]] == [foo] and links["unresolved"] == ["bar-baz"]

    # Deleted for good: still waiting, and a new "Foo" picks it up.
    api.client.delete(f"/api/v1/items/{foo}", headers=AUTH)
    assert api.client.delete(f"/api/v1/items/{foo}?permanent=true", headers=AUTH).status_code == 200
    assert sorted(api.get(f"/items/{plan}/links")["unresolved"]) == ["Foo", "bar-baz"]
    new_foo = capture(api, "Second foo.", title="Foo")
    # A link written as a slug resolves to the item with that slug.
    baz = capture(api, "Baz.", title="Bar Baz")
    api.drain()
    links = api.get(f"/items/{plan}/links")
    assert sorted(link["item"]["id"] for link in links["outgoing"]) == sorted([new_foo, baz])
    assert links["unresolved"] == []


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


def test_saving_never_overwrites_an_edit_made_outside_the_app(api: Api) -> None:
    """Regression: the save compared base_version with the database only, so an edit in another editor that
    the watcher hadn't recorded yet passed the check and was overwritten, with no version keeping it."""
    note = capture(api, "Draft one.", title="Outside")
    api.drain()
    assert api.get(f"/items/{note}/content")["version"] == 1
    path = api.vault.abs(api.get(f"/items/{note}")["path"])
    front, _ = path.read_text(encoding="utf-8").split("\n---\n", 1)
    path.write_text(front + "\n---\nWritten in Obsidian.\n", encoding="utf-8")  # the watcher hasn't seen it

    refused = api.client.put(
        f"/api/v1/items/{note}/content", json={"body": "Saved in UNIVERSE.", "base_version": 1}, headers=AUTH
    )
    assert refused.status_code == 409, refused.text
    assert "Written in Obsidian." in path.read_text(encoding="utf-8")  # the file wasn't touched
    versions = api.get(f"/items/{note}")["versions"]
    assert [v["n"] for v in versions] == [1, 2]  # the outside edit is kept as its own version
    reloaded = api.get(f"/items/{note}/content")
    assert reloaded["version"] == 2 and reloaded["body"].strip() == "Written in Obsidian."
    saved = api.client.put(
        f"/api/v1/items/{note}/content", json={"body": "Saved in UNIVERSE.", "base_version": 2}, headers=AUTH
    )
    assert saved.status_code == 200 and saved.json()["version"] == 3


def test_two_saves_from_the_same_version_never_both_win(api: Api) -> None:
    """Regression: check, write and version weren't atomic, so two saves from one version could both write
    (one silently lost) or fail with a 500 on the versions unique index."""
    import threading

    note = capture(api, "Draft one.", title="Race")
    api.drain()
    barrier = threading.Barrier(2)
    codes: list[int] = []

    def save(text: str) -> None:
        barrier.wait()
        r = api.client.put(f"/api/v1/items/{note}/content", json={"body": text, "base_version": 1}, headers=AUTH)
        codes.append(r.status_code)

    threads = [threading.Thread(target=save, args=(t,)) for t in ("From editor A.", "From editor B.")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(codes) == [200, 409]
    item = api.get(f"/items/{note}")
    assert [v["n"] for v in item["versions"]] == [1, 2]
    body = api.get(f"/items/{note}/content")["body"].strip()
    assert body in ("From editor A.", "From editor B.")


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


def test_a_bad_vector_doesnt_break_the_semantic_layout(api: Api) -> None:
    """Regression: one non-finite vector (LanceDB refuses NaN but stores infinity) made the layout's
    eigendecomposition raise, so the job failed on every retry and the layout never updated. The item with the
    bad vector is left out instead."""
    from universe_vault import jobs
    from universe_vault.vectors import VectorRow

    ids = [capture(api, text) for text in ["my dog", "the puppy", "a kitten", "a sedan car", "the truck"]]
    api.drain()
    api.get("/layout/semantic")
    api.drain()
    conn = api._ctx.conn
    table = conn.execute("SELECT model FROM layout_cache WHERE kind = 'semantic'").fetchone()["model"]
    mean = api._ctx.vectors.item_mean(table, ids[0])
    assert mean is not None
    dim = len(mean)
    bad = [float("inf")] * dim
    api._ctx.vectors.add_many(table, [VectorRow(999_999, ids[0], "note", "2026-01-01T00:00:00.000Z", bad)])
    with conn:
        jobs.enqueue(conn, "layout", priority_class="interactive", idempotency_key="layout:semantic")
    api.drain()
    ready = api.get("/layout/semantic")
    assert ready["status"] == "ready" and sorted(ready["ids"]) == sorted(ids[1:])


def test_notes_from_before_phase_4_get_their_wikilinks_read_once(api: Api) -> None:
    """Regression: wikilinks were only read when a note went through extraction, so notes that existed before
    Phase 4 had no links until edited. Upgrading to schema 5 now reads them once, in the background."""
    import universe_core
    from universe_common.sqlite import migrate_down, migrate_up

    conn = api._ctx.conn
    target = capture(api, "The target.", title="Old target")
    old = capture(api, "Written long ago: see [[Old target]].", title="Old note")
    api.drain()
    # Back to schema 4 with no links, as a Phase 3 vault was; then upgrade it like a real update does.
    directory = Path(universe_core.__file__).parent / "migrations" / "universe"
    migrate_down(conn, directory, 4)
    with conn:
        conn.execute("DELETE FROM links")
    assert api.get(f"/items/{old}/links")["outgoing"] == []
    migrate_up(conn, directory)
    app = cast(FastAPI, api.client.app)
    app.state.ctx.governor.queue_wikilink_backfill()  # Core's housekeeping does this
    api.drain()
    assert [link["item"]["id"] for link in api.get(f"/items/{old}/links")["outgoing"]] == [target]
    # Once: the flag is gone, and a fresh vault never gets one (tests/unit/test_job_queue.py: empty queue).
    assert conn.execute("SELECT 1 FROM settings WHERE key = 'vault.wikilinks_backfill'").fetchone() is None


def test_the_incremental_refresh_misses_nothing(api: Api) -> None:
    """Regressions: (1) a row stamped just before the refresh's server_time but committed after its read was
    never returned by the next `since`; (2) an item deleted for good never showed up in `removed`."""
    late = capture(api, "Committed late.")
    since = api.get("/universe/items")["server_time"]
    conn = api._ctx.conn
    # A worker read the clock a moment before that refresh, but committed after the refresh had read.
    stamp = (datetime.now(UTC) - timedelta(seconds=1)).isoformat(timespec="milliseconds")
    with conn:
        conn.execute("UPDATE items SET updated_at = ? WHERE id = ?", (stamp.replace("+00:00", "Z"), late))
    assert late in api.get("/universe/items", params={"since": since})["ids"]

    gone = capture(api, "Deleted for good.")
    since = api.get("/universe/items")["server_time"]
    assert api.client.delete(f"/api/v1/items/{gone}?permanent=true", headers=AUTH).status_code == 200
    assert gone in api.get("/universe/items", params={"since": since})["removed"]


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
