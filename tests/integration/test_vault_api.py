"""The vault REST API end to end: ingest, items, search, recall, capture, the local API, jobs and workers."""

import json
import threading
import time
import urllib.request
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from tests.conftest import AUTH, free_port
from tests.support import files
from tests.support.fake_ollama import FakeOllama
from universe_core.app import create_app
from universe_core.settings import CoreSettings
from universe_vault.layout import Vault
from universe_vault.worker import EventSink, build_context, drain

BASE = "http://127.0.0.1:47999"


class Api:
    def __init__(self, client: TestClient, settings: CoreSettings, ollama_url: str) -> None:
        self.client = client
        self.vault = Vault(settings.vault_dir)
        token = client.app.state.ctx.internal_token  # type: ignore[attr-defined]

        def post(events: list[dict[str, Any]]) -> None:  # what a worker process does over loopback
            client.post(
                "/api/v1/internal/events", json={"events": events}, headers={"Authorization": f"Bearer {token}"}
            )

        self._ctx = build_context(self.vault, worker_id="test", ollama_url=ollama_url, sink=EventSink(post=post))

    def drain(self) -> int:
        return drain(self._ctx)

    def get(self, path: str, **kw: Any) -> Any:
        response = self.client.get(f"/api/v1{path}", headers=AUTH, **kw)
        assert response.status_code == 200, response.text
        return response.json()

    def post(self, path: str, body: Any = None, expect: int = 200, **kw: Any) -> Any:
        response = self.client.post(f"/api/v1{path}", json=body, headers=kw.pop("headers", AUTH), **kw)
        assert response.status_code == expect, response.text
        return response.json()

    def close(self) -> None:
        self._ctx.conn.close()


@pytest.fixture
def api(make_settings: Callable[..., CoreSettings], fake_ollama: FakeOllama) -> Iterator[Api]:
    settings = make_settings()
    with TestClient(create_app(settings), base_url=BASE) as client:
        a = Api(client, settings, fake_ollama.url)
        yield a
        a.close()


def test_drop_files_then_find_them(api: Api, tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    files.write_pdf(inbox / "lease.pdf", ["Lease for the warehouse on 5th street"])
    (inbox / "car.txt").write_text("The car needs an oil change.", encoding="utf-8")
    project = api.get("/projects")[0]["id"]
    result = api.post(
        "/ingest/paths", {"paths": [str(inbox), "relative/path", str(tmp_path / "nope")], "project_id": project}, 202
    )
    assert result["queued"] == 1 and {r["reason"] for r in result["rejected"]} == {
        "not an absolute path",
        "does not exist",
    }
    api.drain()

    page = api.get("/items")
    assert {i["title"] for i in page["items"]} == {"lease", "car"}
    assert all(i["pipeline_status"] == "done" and i["project_ids"] == [project] for i in page["items"])

    hits = api.get("/search", params={"q": "warehouse"})
    assert hits["hits"][0]["item"]["title"] == "lease" and "«warehouse»" in (hits["hits"][0]["snippet"] or "")
    meaning = api.get("/search", params={"q": "automobile"})
    assert meaning["mode"] == "hybrid" and meaning["hits"][0]["item"]["title"] == "car"
    keyword_only = api.get("/search", params={"q": "automobile", "mode": "keyword"})
    assert all(h["item"]["title"] != "car" for h in keyword_only["hits"])
    filtered = api.get("/search", params={"q": "pdf"})
    assert [h["item"]["title"] for h in filtered["hits"]] == ["lease"] and filtered["parsed"]["types"] == ["pdf"]

    events = api.get("/events", params={"type": "item.*"})["events"]
    assert {e["type"] for e in events} >= {"item.created", "item.processed"}


def test_item_lifecycle(api: Api) -> None:
    created = api.post("/capture", {"text": "Call the surveyor about parcel 88\nThey quoted $450"}, 201)
    api.drain()
    item_id = created["item_id"]
    item = api.get(f"/items/{item_id}")
    assert item["type"] == "note" and item["title"] == "Call the surveyor about parcel 88"
    assert {s["stage"] for s in item["stages"]} == {"metadata", "extract", "embed"}
    assert api.get(f"/items/{item_id}/text")["text"].startswith("Call the surveyor")

    patched = api.client.patch(
        f"/api/v1/items/{item_id}",
        json={"pinned": True, "tags": ["surveyor", "parcel-88"], "status": "active"},
        headers=AUTH,
    ).json()
    assert patched["pinned"] and patched["tags"] == ["parcel-88", "surveyor"] and patched["status"] == "active"
    assert api.get("/search", params={"q": "surveyor", "mode": "keyword"})["hits"][0]["item"]["id"] == item_id

    opened = api.post(f"/items/{item_id}/open")
    assert opened["open_count"] == 1 and Path(opened["abs_path"]).is_file()

    assert api.client.delete(f"/api/v1/items/{item_id}", headers=AUTH).json()["trashed"]
    assert api.get("/items")["items"] == [] and len(api.get("/items", params={"trashed": True})["items"]) == 1
    assert api.post(f"/items/{item_id}/restore")["trashed_at"] is None
    gone = api.client.delete(f"/api/v1/items/{item_id}?permanent=true", headers=AUTH).json()
    assert gone["deleted"]
    assert api.client.get(f"/api/v1/items/{item_id}", headers=AUTH).status_code == 404
    types = [e["type"] for e in api.get("/events", params={"type": "item.*"})["events"]]
    for expected in ("item.created", "item.updated", "item.opened", "item.trashed", "item.restored", "item.deleted"):
        assert expected in types


def test_capture_links_and_files(api: Api, tmp_path: Path) -> None:
    link = api.post("/capture", {"text": "https://example.com/zoning-rules"}, 201)
    files.write_photo(tmp_path / "IMG_77.jpg")
    with (tmp_path / "IMG_77.jpg").open("rb") as fh:
        response = api.client.post(
            "/api/v1/capture/files",
            files={"files": ("IMG_77.jpg", fh, "image/jpeg")},
            data={"source": "clipboard"},
            headers=AUTH,
        )
    assert response.status_code == 202 and response.json()["queued_files"] == 1
    api.drain()
    items = {i["title"]: i for i in api.get("/items")["items"]}
    assert items["https://example.com/zoning-rules"]["type"] == "link" and link["status"] == "created"
    photo = items["IMG_77"]
    assert photo["type"] == "photo" and photo["has_thumbnail"]
    thumb = api.client.get(f"/api/v1/items/{photo['id']}/thumbnail", headers=AUTH)
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/webp"
    original = api.client.get(f"/api/v1/items/{photo['id']}/file", headers=AUTH)
    assert original.content == (tmp_path / "IMG_77.jpg").read_bytes()
    assert not list((api.vault.cache / "uploads").iterdir())  # the staged upload was cleaned up


def test_recall_fast_path(api: Api) -> None:
    api.post("/capture", {"text": "Ember Wolf offer letter for parcel 4471", "title": "Offer letter 4471"}, 201)
    api.post("/capture", {"text": "Grocery list: eggs, milk"}, 201)
    api.drain()
    go = api.post("/recall", {"q": "go to ember wolf"})
    assert go["action"] == "show_project" and go["target_id"] == api.get("/projects")[0]["id"]
    opened = api.post("/recall", {"q": "open offer letter 4471"})
    assert opened["intent"] == "open" and opened["action"] == "open_item" and opened["confidence"] >= 0.85
    shown = api.post("/recall", {"q": "show notes"})
    assert shown["action"] == "show_results" and shown["parsed"]["types"] == ["note"] and len(shown["hits"]) == 2
    assert opened["took_ms"] < 1000


def test_local_api_keys_are_scoped_and_revocable(api: Api) -> None:
    created = api.post("/api-keys", {"name": "my script", "scopes": ["capture"]}, 201)
    key = created["key"]
    assert key.startswith("uk_") and created["info"]["prefix"] == key[:7]
    script = {"Authorization": f"Bearer {key}"}
    api.post("/capture", {"text": "from a script"}, 201, headers=script)
    assert api.client.get("/api/v1/search?q=script", headers=script).status_code == 403  # no search scope
    assert api.client.get("/api/v1/items", headers=script).status_code == 401  # never the full API
    assert api.client.get("/api/v1/search?q=x", headers={"Authorization": "Bearer uk_wrong"}).status_code == 401
    listed = api.get("/api-keys")
    assert listed[0]["last_used_at"] is not None and "key" not in listed[0]
    api.client.delete(f"/api/v1/api-keys/{created['info']['id']}", headers=AUTH)
    assert api.client.post("/api/v1/capture", json={"text": "late"}, headers=script).status_code == 401
    actions = [e["action"] for e in api.get("/audit")]
    assert "api_key.created" in actions and "api_key.revoked" in actions


def test_internal_endpoints_need_the_internal_token(api: Api) -> None:
    body = {"events": [{"type": "item.processed", "payload": {"item_id": "x"}}]}
    assert api.client.post("/api/v1/internal/events", json=body, headers=AUTH).status_code == 401
    token = api.client.app.state.ctx.internal_token  # type: ignore[attr-defined]
    internal = {"Authorization": f"Bearer {token}"}
    ok = api.client.post("/api/v1/internal/events", json=body, headers=internal)
    assert ok.json() == {"published": 1}
    sneaky = {"events": [{"type": "killswitch.released", "payload": {}}]}  # workers can't publish safety events
    assert api.client.post("/api/v1/internal/events", json=sneaky, headers=internal).json() == {"published": 0}


def test_queue_pause_resume_and_stats(api: Api) -> None:
    api.post("/capture", {"text": "queued while paused"}, 201)
    assert api.post("/queue/pause")["paused"]
    assert api.drain() == 0
    stats = api.get("/jobs/stats")
    assert stats["by_kind"]["pipeline"] == 1 and stats["pause_reason"] == "paused by you"
    assert not api.post("/queue/resume")["paused"]
    assert api.drain() >= 2
    assert api.get("/jobs/stats")["queued"] == 0
    assert api.get("/system/vault")["items"] == 1


def _http(method: str, url: str, body: Any = None) -> Any:
    request = urllib.request.Request(url, method=method, headers={**AUTH, "Content-Type": "application/json"})
    data = json.dumps(body).encode() if body is not None else None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, data=data, timeout=10) as response:
        return json.loads(response.read() or b"null")


@pytest.mark.slow
def test_a_real_worker_process_runs_the_pipeline(make_settings: Callable[..., CoreSettings], tmp_path: Path) -> None:
    """Real Core (uvicorn on a port) + a real worker process: the production path, events included."""
    port = free_port()
    settings = make_settings(workers=1, port=port)
    note = tmp_path / "field-notes.md"
    note.write_text("# Field notes\nThe heron came back to the pond.\n", encoding="utf-8")
    server = uvicorn.Server(uvicorn.Config(create_app(settings), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    core = f"http://127.0.0.1:{port}/api/v1"
    try:
        deadline = time.monotonic() + 20
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        assert _http("POST", f"{core}/ingest/paths", {"paths": [str(note)]})["queued"] == 1
        deadline = time.monotonic() + 60
        items: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            items = _http("GET", f"{core}/items")["items"]
            if items and items[0]["pipeline_status"] == "done":
                break
            time.sleep(0.2)
        assert items and items[0]["title"] == "Field notes" and items[0]["pipeline_status"] == "done"
        workers = _http("GET", f"{core}/system/vault")["workers"]
        assert workers[0]["state"] == "running" and workers[0]["pid"]
        # Events from the worker process reached Core over the internal endpoint.
        events = _http("GET", f"{core}/events?type=item.*")["events"]
        assert any(e["type"] == "item.processed" and e["source"] == "worker" for e in events)
    finally:
        server.should_exit = True
        thread.join(timeout=15)


def test_embedding_and_vision_model_assignments(api: Api, fake_ollama: FakeOllama) -> None:
    put = api.client.put
    wrong = put("/api/v1/models/assignments", json={"tier": "embed_text", "model": "fake-chat:latest"}, headers=AUTH)
    assert wrong.status_code == 400 and "embedding" in wrong.json()["detail"]
    ok = put("/api/v1/models/assignments", json={"tier": "embed_text", "model": "fake-embed:latest"}, headers=AUTH)
    assert ok.status_code == 200 and ok.json()["assignments"]["embed_text"] == "fake-embed:latest"
    assert (
        put(
            "/api/v1/models/assignments", json={"tier": "vision", "model": "fake-vision:latest"}, headers=AUTH
        ).status_code
        == 400
    )
    fake_ollama.with_vision = True
    assert (
        put(
            "/api/v1/models/assignments", json={"tier": "vision", "model": "fake-vision:latest"}, headers=AUTH
        ).status_code
        == 200
    )
    cleared = api.client.delete("/api/v1/models/assignments/vision", headers=AUTH).json()
    assert "vision" not in cleared["assignments"]


def test_item_pages_walk_everything_once_and_count_on_the_first_page(api: Api) -> None:
    for i in range(5):
        api.post("/capture", {"text": f"Paging note {i}"}, 201)
    first = api.get("/items", params={"limit": 2})
    assert first["total"] == 5 and len(first["items"]) == 2 and first["next_cursor"]
    seen = [i["id"] for i in first["items"]]
    cursor = first["next_cursor"]
    while cursor:
        page = api.get("/items", params={"limit": 2, "cursor": cursor})
        assert page["total"] is None  # later pages skip the count
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
    assert len(seen) == len(set(seen)) == 5
    assert api.get("/items", params={"type": "pdf"})["total"] == 0  # the count follows the filters


# ---------- review 2026-10-22: regressions ----------


def test_an_upload_that_is_too_large_leaves_nothing_behind(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file being written when the size limit hit wasn't in the cleanup list yet: it stayed in the cache."""
    from universe_core import vault_api

    monkeypatch.setattr(vault_api, "MAX_UPLOAD_BYTES", 10)
    response = api.client.post(
        "/api/v1/capture/files",
        files=[("files", ("small.txt", b"ok", "text/plain")), ("files", ("big.txt", b"x" * 100, "text/plain"))],
        headers=AUTH,
    )
    assert response.status_code == 413
    assert not list((api.vault.cache / "uploads").iterdir())


def test_an_upload_that_cannot_be_queued_leaves_nothing_behind(api: Api, monkeypatch: pytest.MonkeyPatch) -> None:
    from universe_core import vault_api

    def broken(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("the job queue is unavailable")

    monkeypatch.setattr(vault_api.jobs, "enqueue", broken)
    with pytest.raises(RuntimeError, match="job queue"):
        api.client.post("/api/v1/capture/files", files={"files": ("a.txt", b"hello", "text/plain")}, headers=AUTH)
    assert not list((api.vault.cache / "uploads").iterdir())


def test_a_thumbnail_id_must_be_an_item_id(api: Api) -> None:
    """The id went straight into the file path; on Windows `..%5C` (a backslash) walks out of the thumbnails."""
    api.vault.thumbs.mkdir(parents=True, exist_ok=True)
    # On Linux a backslash is an ordinary character, so plant the file Windows would reach through `..\`.
    (api.vault.thumbs / "..\\secret.webp").write_bytes(b"not a thumbnail")
    response = api.client.get("/api/v1/items/..%5Csecret/thumbnail", headers=AUTH)
    assert response.status_code == 404
