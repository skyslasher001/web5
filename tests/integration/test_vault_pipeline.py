"""Files of every core type go in, run through the real pipeline (in-process worker), and come back out of
search by keyword, by fragment and by meaning. Plus dedupe, versions, trash and real deletion."""

import json
import sqlite3
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from tests.support import files
from tests.support.fake_ollama import CAPTION, VISION_MODEL, FakeOllama, fake_embedding
from universe_common.sqlite import connect, transaction
from universe_core.db import Databases
from universe_core.events import EventBus
from universe_core.seed import ensure_seed_galaxies
from universe_vault import ingest, jobs, purge, search, store
from universe_vault.handlers import WorkerContext
from universe_vault.layout import Vault, sidecar_path
from universe_vault.models import query_prefix
from universe_vault.query import Project, parse
from universe_vault.vectors import table_name
from universe_vault.worker import EventSink, build_context, drain

EMBED_TABLE = table_name("fake-embed:latest", "bbb")


def _row(conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
    row = store.get_row(conn, item_id)
    assert row is not None, f"item {item_id} is missing"
    return row


@dataclass
class Rig:
    vault: Vault
    conn: sqlite3.Connection
    ctx: WorkerContext
    events: list[dict[str, Any]] = field(default_factory=list)
    errors: list[tuple[str, str]] = field(default_factory=list)

    def project(self, slug: str) -> str:
        return self.conn.execute("SELECT id FROM projects WHERE slug = ?", (slug,)).fetchone()["id"]

    def projects(self) -> list[Project]:
        return [Project(r["id"], r["name"], r["slug"]) for r in self.conn.execute("SELECT * FROM projects")]

    def run(self) -> int:
        return drain(self.ctx)

    def import_path(self, path: Path, **payload: Any) -> None:
        jobs.enqueue(
            self.conn,
            "import",
            payload={"path": str(path), "source_kind": "drop", **payload},
            priority_class="interactive",
        )

    def find(self, q: str, *, semantic: bool = True, **filters: Any) -> list[str]:
        parsed = parse(q, self.projects())
        vector = fake_embedding(query_prefix("fake-embed") + parsed.text) if semantic and parsed.text else None
        response = search.search(
            self.conn,
            self.vault,
            parsed,
            search.Filters(**filters),
            vectors=self.ctx.vectors,
            vector=vector,
            vector_table=EMBED_TABLE if vector else None,
            query=q,
        )
        return [h.item.title for h in response.hits]


@pytest.fixture
def rig(tmp_path: Path, fake_ollama: FakeOllama) -> Iterator[Rig]:
    vault = Vault(tmp_path / "vault")
    vault.ensure()
    dbs = Databases.open(vault.index)
    ensure_seed_galaxies(dbs.universe, EventBus(dbs.events))
    dbs.close()
    conn = connect(vault.db_path)
    events: list[dict[str, Any]] = []
    errors: list[tuple[str, str]] = []
    sink = EventSink(post=events.extend)
    ctx = build_context(vault, worker_id="test-worker", ollama_url=fake_ollama.url, sink=sink, conn=conn)
    ctx.report_error = lambda kind, message, _stack: errors.append((kind, message))
    yield Rig(vault, conn, ctx, events, errors)
    if ctx.ollama:
        ctx.ollama.close()
    conn.close()


def make_inbox(folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    files.write_pdf(
        folder / "parcel-4471-agreement.pdf",
        ["Purchase agreement for parcel 4471", "The lake house closes in November"],
    )
    files.write_docx(folder / "pricing.docx", "Pricing tool tiers", ["Tier one costs nine dollars a month."])
    files.write_xlsx(folder / "survey-budget.xlsx", {"Budget": [["Item", "Cost"], ["Boundary survey", 450]]})
    files.write_pptx(folder / "roadmap.pptx", [("Roadmap", "Ship the vault before the holidays")])
    (folder / "seller-call.md").write_text(
        "---\ntitle: Seller call\n---\nOwner wants out by November.\n", encoding="utf-8"
    )
    (folder / "garage.txt").write_text("My car needs new tires before the road trip.\n", encoding="utf-8")
    (folder / "main.py").write_text("def quantum_flux():\n    return 42\n", encoding="utf-8")
    files.write_photo(folder / "IMG_2041.jpg", gps=(30.2672, -97.7431))
    files.write_text_image(folder / "receipt-scan.png", "Hardware store receipt 8812")
    files.write_wav(folder / "take3.wav", title="Ember Night", artist="Sky Slasher", album="Demos")
    (folder / "node_modules").mkdir()
    (folder / "node_modules" / "skip.js").write_text("ignored")
    return folder


def test_mixed_folder_goes_through_the_whole_pipeline(rig: Rig, tmp_path: Path) -> None:
    inbox = make_inbox(tmp_path / "inbox")
    rig.import_path(inbox, project_ids=[rig.project("ember-wolf-acquisitions")])
    rig.run()

    rows = {r["title"]: r for r in rig.conn.execute("SELECT * FROM items")}
    assert set(rows) == {
        "parcel-4471-agreement",
        "pricing",
        "survey-budget",
        "roadmap",
        "Seller call",
        "garage",
        "main",
        "IMG_2041",
        "receipt-scan",
        "take3",
    }  # node_modules was skipped
    assert {r["pipeline_status"] for r in rows.values()} == {"done"}
    assert rows["IMG_2041"]["type"] == "photo" and rows["IMG_2041"]["path"].startswith("photos/2024/07/")
    assert rows["take3"]["type"] == "audio"

    photo = json.loads(rows["IMG_2041"]["metadata"])
    assert photo["camera"] == "Canon EOS R6" and rows["IMG_2041"]["lat"] == pytest.approx(30.2672)
    assert rig.vault.thumb_path(rows["IMG_2041"]["id"]).exists()
    audio = json.loads(rows["take3"]["metadata"])
    assert audio["artist"] == "Sky Slasher"
    stages = {s.stage: s for s in store.stages(rig.conn, rows["take3"]["id"])}
    assert stages["transcribe"].status == "skipped" and "Phase 7" in (stages["transcribe"].detail or "")

    # Originals are copied byte for byte; the source folder is untouched.
    pdf_row = rows["parcel-4471-agreement"]
    assert rig.vault.abs(pdf_row["path"]).read_bytes() == (inbox / "parcel-4471-agreement.pdf").read_bytes()
    assert (inbox / "parcel-4471-agreement.pdf").exists()
    # Non-note items get a sidecar; notes don't.
    side = json.loads(sidecar_path(rig.vault.abs(pdf_row["path"])).read_text())
    assert side["id"] == pdf_row["id"] and side["projects"] == ["ember-wolf-acquisitions"]
    assert not sidecar_path(rig.vault.abs(rows["Seller call"]["path"])).exists()
    # Every item is embedded.
    for row in rows.values():
        assert rig.ctx.vectors.count(EMBED_TABLE, row["id"]) >= 1

    types = [e["type"] for e in rig.events]
    assert types.count("item.created") == 10 and types.count("item.processed") == 10


def test_found_by_keyword_fragment_meaning_and_filters(rig: Rig, tmp_path: Path) -> None:
    rig.import_path(make_inbox(tmp_path / "inbox"))
    rig.run()

    assert rig.find("lake house", semantic=False)[0] == "parcel-4471-agreement"  # text on page 2
    assert rig.find("nine dollars")[0] == "pricing"
    assert rig.find("boundary survey")[0] == "survey-budget"
    assert rig.find("4471", semantic=False)[0] == "parcel-4471-agreement"
    assert rig.find("receipt 8812", semantic=False)[0] == "receipt-scan"  # OCR text
    assert rig.find("quantum_flux")[0] == "main"
    assert rig.find("Sky Slasher")[0] == "take3"  # audio tags
    # Meaning, not words: "automobile" never appears, "car" does.
    assert "garage" not in rig.find("automobile", semantic=False)
    assert rig.find("automobile")[0] == "garage"
    # Filters parsed from the query.
    assert set(rig.find("photos")) == {"receipt-scan", "IMG_2041"}
    assert rig.find("pdf about the lake")[0] == "parcel-4471-agreement"


def test_meaning_matches_must_be_related_and_show_real_text(rig: Rig, tmp_path: Path) -> None:
    # Regression: the nearest neighbours of any query used to come back as "found", with the metadata
    # chunk ("shopping document") as their snippet.
    inbox = tmp_path / "notes"
    inbox.mkdir()
    (inbox / "river-walk.txt").write_text("My puppy loves walking along the river every morning.\n")
    (inbox / "shopping.txt").write_text("eggs, flour, sugar, butter\n")
    rig.import_path(inbox)
    rig.run()

    assert rig.find("dog near water") == ["river-walk"]  # dog ≈ puppy, water ≈ river; nothing in common with eggs
    assert rig.find("accountant") == []  # no word and no meaning in common with anything
    item_id = rig.conn.execute("SELECT id FROM items WHERE title = 'river-walk'").fetchone()["id"]
    metadata_chunk = rig.conn.execute(
        "SELECT id FROM chunks WHERE item_id = ? AND kind = 'metadata'", (item_id,)
    ).fetchone()["id"]
    assert str(search._excerpt(rig.conn, metadata_chunk, "dog")).startswith("My puppy loves walking")


def test_duplicates_are_recognised_and_gain_projects(rig: Rig, tmp_path: Path) -> None:
    source = files.write_pdf(tmp_path / "deal.pdf", ["Same bytes"])
    first = ingest.import_file(rig.conn, rig.vault, source, source_kind="drop")
    copy = tmp_path / "copy-of-deal.pdf"
    copy.write_bytes(source.read_bytes())
    second = ingest.import_file(rig.conn, rig.vault, copy, source_kind="drop", project_ids=[rig.project("devmind")])
    assert first.status == "created" and second.status == "duplicate" and second.item_id == first.item_id
    assert second.project_ids_added == [rig.project("devmind")]
    assert rig.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1


def test_editing_a_note_on_disk_keeps_every_version(rig: Rig, tmp_path: Path) -> None:
    item_id = ingest.create_note(rig.conn, rig.vault, "Sketch of a pelican by the water", title="Bird sketches")
    rig.run()
    path = rig.vault.abs(_row(rig.conn, item_id)["path"])
    assert path.read_text().startswith("---\nid: " + item_id)  # Obsidian-compatible frontmatter
    path.write_text(path.read_text().replace("pelican", "heron"), encoding="utf-8")
    assert ingest.add_version(rig.conn, rig.vault, item_id, new_source=None, actor="user") == 2
    assert ingest.add_version(rig.conn, rig.vault, item_id, new_source=None, actor="user") is None  # no change
    rig.run()
    versions = rig.conn.execute("SELECT n, path FROM versions WHERE item_id = ? ORDER BY n", (item_id,)).fetchall()
    assert [v["n"] for v in versions] == [1, 2]
    assert "pelican" in rig.vault.abs(versions[0]["path"]).read_text()
    assert "heron" in rig.vault.abs(versions[1]["path"]).read_text()
    assert rig.find("heron", semantic=False) == ["Bird sketches"]
    assert rig.find("pelican", semantic=False) == []  # the index follows the current version


def test_trash_restore_and_purge_leave_no_trace(rig: Rig, tmp_path: Path) -> None:
    files.write_photo(tmp_path / "IMG_9.jpg")
    result = ingest.import_file(rig.conn, rig.vault, tmp_path / "IMG_9.jpg", source_kind="drop")
    rig.run()
    item_id = str(result.item_id)
    original = rig.vault.abs(_row(rig.conn, item_id)["path"])
    assert original.exists() and sidecar_path(original).exists() and rig.vault.thumb_path(item_id).exists()

    assert purge.trash(rig.conn, rig.vault, item_id)
    assert not original.exists() and rig.find("IMG_9", semantic=False) == []
    assert purge.restore(rig.conn, rig.vault, item_id)
    assert original.exists() and rig.find("IMG_9", semantic=False) == ["IMG_9"]

    assert purge.purge(rig.conn, rig.vault, rig.ctx.vectors, item_id)
    assert not original.exists() and not sidecar_path(original).exists()
    assert not rig.vault.thumb_path(item_id).exists()
    for table in ("items", "versions", "item_stages", "chunks", "jobs"):
        column = "id" if table == "items" else "item_id"
        assert rig.conn.execute(f"SELECT COUNT(*) FROM {table} WHERE {column} = ?", (item_id,)).fetchone()[0] == 0  # noqa: S608
    assert rig.conn.execute("SELECT COUNT(*) FROM items_fts WHERE item_id = ?", (item_id,)).fetchone()[0] == 0
    assert rig.conn.execute("SELECT COUNT(*) FROM chunks_fts WHERE chunks_fts MATCH 'IMG_9'").fetchone()[0] == 0
    assert rig.ctx.vectors.count(EMBED_TABLE, item_id) == 0


def test_without_an_embedding_model_items_still_finish(tmp_path: Path) -> None:
    server = FakeOllama(with_models=False).start()
    try:
        vault = Vault(tmp_path / "v")
        vault.ensure()
        Databases.open(vault.index).close()
        ctx = build_context(vault, worker_id="w", ollama_url=server.url)
        item_id = ingest.create_note(ctx.conn, vault, "A note with no embedder around")
        drain(ctx)
        stage = {s.stage: s for s in store.stages(ctx.conn, item_id)}["embed"]
        assert stage.status == "skipped" and "ollama pull" in (stage.detail or "")
        assert _row(ctx.conn, item_id)["pipeline_status"] == "done"
        ctx.conn.close()
    finally:
        server.stop()


def test_ollama_down_means_waiting_not_failing(tmp_path: Path) -> None:
    vault = Vault(tmp_path / "v")
    vault.ensure()
    Databases.open(vault.index).close()
    ctx = build_context(vault, worker_id="w", ollama_url="http://127.0.0.1:9")
    item_id = ingest.create_note(ctx.conn, vault, "Waiting for Ollama")
    drain(ctx)
    stage = {s.stage: s for s in store.stages(ctx.conn, item_id)}["embed"]
    assert stage.status == "pending" and stage.detail == "waiting for Ollama"
    job = ctx.conn.execute("SELECT status, attempts FROM jobs WHERE kind = 'embed'").fetchone()
    assert job["status"] == "queued" and job["attempts"] == 0  # released, not failed
    ctx.conn.close()


def test_embedding_errors_retry_then_are_reported(rig: Rig, fake_ollama: FakeOllama) -> None:
    fake_ollama.embed_status = 500
    item_id = ingest.create_note(rig.conn, rig.vault, "Embedding will fail")
    rig.run()  # pipeline succeeds, then the embed job fails once and backs off
    stage = {s.stage: s for s in store.stages(rig.conn, item_id)}["embed"]
    assert stage.status == "failed" and "500" in (stage.error or "")
    assert _row(rig.conn, item_id)["pipeline_status"] == "failed"
    with transaction(rig.conn):
        rig.conn.execute(
            "UPDATE jobs SET max_attempts = 2, run_after = '2000-01-01T00:00:00.000Z' WHERE kind = 'embed'"
        )
    rig.run()
    assert rig.conn.execute("SELECT status FROM jobs WHERE kind = 'embed'").fetchone()["status"] == "dead"
    assert rig.errors and "500" in rig.errors[0][1]
    assert "job.dead" in [e["type"] for e in rig.events]
    fake_ollama.embed_status = 200
    job_id = rig.conn.execute("SELECT id FROM jobs WHERE kind = 'embed'").fetchone()["id"]
    assert jobs.retry(rig.conn, job_id)
    rig.run()
    assert _row(rig.conn, item_id)["pipeline_status"] == "done"


def test_captions_from_an_assigned_vision_model(rig: Rig, fake_ollama: FakeOllama, tmp_path: Path) -> None:
    fake_ollama.with_vision = True
    rig.conn.execute("INSERT INTO settings (key, value, updated_at) VALUES ('model.vision', ?, 'now')", (VISION_MODEL,))
    files.write_photo(tmp_path / "dock.jpg")
    result = ingest.import_file(rig.conn, rig.vault, tmp_path / "dock.jpg", source_kind="drop")
    rig.run()
    row = _row(rig.conn, str(result.item_id))
    assert json.loads(row["metadata"])["caption"] == CAPTION
    assert json.loads(sidecar_path(rig.vault.abs(row["path"])).read_text())["caption"] == CAPTION
    assert rig.find("dusk on the water")[0] == "dock"  # caption + concept embeddings: meaning, not words
