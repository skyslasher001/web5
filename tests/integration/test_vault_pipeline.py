"""Files of every core type go in, run through the real pipeline (in-process worker), and come back out of
search by keyword, by fragment and by meaning. Plus dedupe, versions, trash and real deletion."""

import json
import os
import sqlite3
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from watchdog.events import FileMovedEvent

from tests.support import files
from tests.support.fake_ollama import CAPTION, VISION_MODEL, FakeOllama, fake_embedding
from tests.support.fake_voice import FakeSTT, utterances
from universe_common.sqlite import connect, transaction
from universe_core.db import Databases
from universe_core.events import EventBus
from universe_core.seed import ensure_seed_galaxies
from universe_vault import ingest, jobs, pipeline, purge, search, store
from universe_vault.handlers import WorkerContext
from universe_vault.layout import Vault, sidecar_path
from universe_vault.models import query_prefix
from universe_vault.query import Project, parse
from universe_vault.transcription import NO_STT, Transcriber
from universe_vault.vectors import table_name
from universe_vault.watch import VAULT, Watcher, _Handler
from universe_vault.worker import EventSink, build_context, drain
from universe_voice import longform
from universe_voice.audio import STT_RATE, resample, write_wav
from universe_voice.vad import EnergyVAD

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
    ctx = build_context(
        vault,
        worker_id="test-worker",
        ollama_url=fake_ollama.url,
        sink=sink,
        conn=conn,
        voice_models=tmp_path / "models" / "voice",  # empty: no Whisper installed
    )
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
    assert stages["transcribe"].status == "skipped" and stages["transcribe"].detail == NO_STT

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


def test_voice_memos_are_transcribed_with_timestamps(rig: Rig, tmp_path: Path) -> None:
    """SPEC §11 "voice memos are transcribed into the vault automatically", §5.5 "with timestamps"."""
    stt = FakeSTT(["Ember Wolf needs a bridge in the second verse.", "Call the seller about the lake parcel."])
    rig.ctx.transcriber = Transcriber(tmp_path, engines=lambda: (stt, EnergyVAD()))
    memo = tmp_path / "memo.wav"
    audio = utterances(("pause", 1.0), ("speech", 1.5), ("pause", 2.0), ("speech", 1.0), ("pause", 1.0))
    write_wav(memo, resample(audio, STT_RATE, 44_100), 44_100)  # a phone-style rate: resampled on the way in
    result = ingest.import_file(rig.conn, rig.vault, memo, source_kind="quick_capture", item_type="voice_memo")
    assert result.item_id is not None
    rig.run()

    row = _row(rig.conn, result.item_id)
    assert row["type"] == "voice_memo" and row["pipeline_status"] == "done"
    stage = {s.stage: s for s in store.stages(rig.conn, result.item_id)}["transcribe"]
    assert stage.status == "done" and json.loads(stage.detail or "{}")["segments"] == 2
    chunks = [c for c in store.item_chunks(rig.conn, result.item_id) if c["kind"] == "text"]
    assert [c["text"] for c in chunks] == [
        "Ember Wolf needs a bridge in the second verse.",
        "Call the seller about the lake parcel.",
    ]
    # Each segment knows where it is in the recording (speech at 1.0–2.5 s and 4.5–5.5 s, ± padding).
    assert 700 <= chunks[0]["start_ms"] <= 1000 and 2500 <= chunks[0]["end_ms"] <= 2900
    assert 4200 <= chunks[1]["start_ms"] <= 4500 and 5500 <= chunks[1]["end_ms"] <= 5900
    assert stt.heard and all(s < 3.0 for s in stt.heard)  # one utterance at a time, not the whole file
    assert rig.find("lake parcel", semantic=False) == ["memo"]
    sidecar = json.loads(sidecar_path(rig.vault.abs(row["path"])).read_text(encoding="utf-8"))
    assert [s["text"] for s in sidecar["transcript"]][1] == "Call the seller about the lake parcel."


def test_installing_whisper_transcribes_what_was_skipped(rig: Rig, tmp_path: Path) -> None:
    idea = tmp_path / "idea.wav"
    write_wav(idea, utterances(("pause", 0.5), ("speech", 1.0), ("pause", 0.5)), STT_RATE)
    rig.import_path(idea)
    rig.run()
    item_id = rig.conn.execute("SELECT id FROM items").fetchone()["id"]
    assert {s.stage: s for s in store.stages(rig.conn, item_id)}["transcribe"].detail == NO_STT

    stt = FakeSTT(["a melody for the chorus"])
    rig.ctx.transcriber = Transcriber(tmp_path, engines=lambda: (stt, EnergyVAD()))
    assert pipeline.requeue_untranscribed(rig.conn, NO_STT) == 1
    rig.run()
    assert {s.stage: s for s in store.stages(rig.conn, item_id)}["transcribe"].status == "done"
    assert rig.find("melody chorus", semantic=False) == ["idea"]
    assert pipeline.requeue_untranscribed(rig.conn, NO_STT) == 0


def test_formats_without_a_decoder_say_why(rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(longform, "ffmpeg", lambda: None)
    rig.ctx.transcriber = Transcriber(tmp_path, engines=lambda: (FakeSTT(), EnergyVAD()))
    song = tmp_path / "demo.mp3"
    song.write_bytes(b"ID3" + bytes(64))
    rig.import_path(song)
    rig.run()
    item_id = rig.conn.execute("SELECT id FROM items").fetchone()["id"]
    stage = {s.stage: s for s in store.stages(rig.conn, item_id)}["transcribe"]
    assert stage.status == "skipped" and "needs ffmpeg on PATH" in (stage.detail or "")
    assert _row(rig.conn, item_id)["pipeline_status"] == "done"


# ---------- review fixes (2026-10-22): regressions ----------


def _vault_file(rig: Rig, path: Path, event: str, **extra: Any) -> None:
    """Queue what the vault watcher queues for a file event, then run it."""
    jobs.enqueue(rig.conn, "vault_file", payload={"path": str(path), "event": event, **extra})
    rig.run()


def test_purging_a_trashed_item_never_deletes_a_newer_item_at_its_old_path(rig: Rig, tmp_path: Path) -> None:
    """Regression: purge unlinked every versions.path of the item, but trash leaves the old version rows pointing
    at the original location, which a new item with the same name takes: purging A deleted B's file."""
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "report.txt").write_text("First report about the lake", encoding="utf-8")
    first = ingest.import_file(rig.conn, rig.vault, tmp_path / "a" / "report.txt", source_kind="drop")
    rig.run()
    old_path = _row(rig.conn, str(first.item_id))["path"]
    assert purge.trash(rig.conn, rig.vault, str(first.item_id))
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "report.txt").write_text("Second report about the house", encoding="utf-8")
    second = ingest.import_file(rig.conn, rig.vault, tmp_path / "b" / "report.txt", source_kind="drop")
    assert second.path == old_path  # the name was free again
    assert purge.purge(rig.conn, rig.vault, rig.ctx.vectors, str(first.item_id))
    assert rig.vault.abs(old_path).read_text(encoding="utf-8") == "Second report about the house"


def test_a_file_recreated_where_one_was_deleted_outside_the_app_is_indexed(rig: Rig) -> None:
    """Regression: an item whose file was deleted outside the app kept its (UNIQUE) path, and find_by_path
    returned trashed rows, so a new file at that path was never indexed and purging the old item deleted it."""
    hand = rig.vault.root / "documents" / "hand-placed.txt"
    hand.parent.mkdir(parents=True, exist_ok=True)
    hand.write_text("Put here by hand", encoding="utf-8")
    _vault_file(rig, hand, "changed")
    old_id = rig.conn.execute("SELECT id FROM items").fetchone()["id"]
    hand.unlink()
    _vault_file(rig, hand, "deleted")
    assert _row(rig.conn, old_id)["trashed_at"] is not None
    with pytest.raises(purge.PurgeError, match="deleted outside"):
        purge.restore(rig.conn, rig.vault, old_id)

    hand.write_text("A new file with the same name", encoding="utf-8")
    _vault_file(rig, hand, "changed")
    live = rig.conn.execute("SELECT id, path FROM items WHERE trashed_at IS NULL").fetchall()
    assert [r["path"] for r in live] == ["documents/hand-placed.txt"] and live[0]["id"] != old_id
    assert rig.find("same name", semantic=False) == ["hand-placed"]
    assert purge.purge(rig.conn, rig.vault, rig.ctx.vectors, old_id)
    assert hand.read_text(encoding="utf-8") == "A new file with the same name"


def test_two_imports_racing_for_one_name_never_overwrite_each_other(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: free_path picked a name, then os.replace put the copy there even if another importer had
    taken the name meanwhile: its file was overwritten (and the cleanup could unlink a file it didn't own)."""
    real_copy = ingest.shutil.copy2
    raced: list[Path] = []

    def copy_while_another_import_wins(src: Any, dst: Any, **kwargs: Any) -> Any:
        if not raced:
            winner = Path(dst).parent / "report.txt"  # the other importer takes the name first
            winner.write_text("the other import's bytes", encoding="utf-8")
            raced.append(winner)
        return real_copy(src, dst, **kwargs)

    monkeypatch.setattr(ingest.shutil, "copy2", copy_while_another_import_wins)
    (tmp_path / "report.txt").write_text("this import's bytes", encoding="utf-8")
    result = ingest.import_file(rig.conn, rig.vault, tmp_path / "report.txt", source_kind="drop")
    assert raced and raced[0].read_text(encoding="utf-8") == "the other import's bytes"
    assert result.path is not None and result.path.endswith("report (2).txt")
    assert rig.vault.abs(result.path).read_text(encoding="utf-8") == "this import's bytes"
    assert not [p for p in raced[0].parent.iterdir() if p.name.endswith(".part")]


def test_renaming_a_file_inside_the_vault_keeps_the_item(rig: Rig, tmp_path: Path) -> None:
    """Regression: the vault watcher turned a rename into delete + import, so the item lost its tags, links,
    galaxies and history (the old one went to the trash, a new one was created)."""
    (tmp_path / "plan.txt").write_text("The cabin plan", encoding="utf-8")
    item_id = str(ingest.import_file(rig.conn, rig.vault, tmp_path / "plan.txt", source_kind="drop").item_id)
    rig.run()
    with transaction(rig.conn):
        store.set_tags(rig.conn, item_id, ["cabin"], "user")
    old = rig.vault.abs(_row(rig.conn, item_id)["path"])
    new = old.with_name("cabin-plan.txt")
    old.rename(new)

    queued: list[tuple[str, dict[str, Any]]] = []
    watcher = Watcher(rig.vault, lambda kind, payload: queued.append((kind, payload)), debounce_s=0)
    _Handler(watcher, VAULT).on_moved(FileMovedEvent(str(old), str(new)))
    watcher.settle(now=1e12)
    watcher.settle(now=2e12)
    for kind, payload in queued:
        jobs.enqueue(rig.conn, kind, payload=payload)
    rig.run()

    assert rig.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0] == 1
    row = _row(rig.conn, item_id)
    assert row["trashed_at"] is None and row["path"] == rig.vault.rel(new)
    item = store.get_item(rig.conn, rig.vault, item_id)
    assert item is not None and item.tags == ["cabin"]
    assert sidecar_path(new).exists() and not sidecar_path(old).exists()


def test_new_versions_hash_and_copy_outside_the_write_transaction(
    rig: Rig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: add_version hashed and copied whole files inside BEGIN IMMEDIATE, holding the database's
    write lock for as long as a large file takes to read."""
    source = tmp_path / "watched" / "budget.txt"
    source.parent.mkdir()
    source.write_text("Budget v1", encoding="utf-8")
    item_id = str(ingest.import_file(rig.conn, rig.vault, source, source_kind="drop").item_id)
    note_id = ingest.create_note(rig.conn, rig.vault, "Draft one", title="Draft")
    rig.run()
    in_transaction: list[tuple[str, bool]] = []
    real_hash, real_copy = ingest.sha256_file, ingest.shutil.copy2

    def hash_spy(path: Path) -> str:
        in_transaction.append(("hash", rig.conn.in_transaction))
        return real_hash(path)

    def copy_spy(src: Any, dst: Any, **kwargs: Any) -> Any:
        in_transaction.append(("copy", rig.conn.in_transaction))
        return real_copy(src, dst, **kwargs)

    monkeypatch.setattr(ingest, "sha256_file", hash_spy)
    monkeypatch.setattr(ingest.shutil, "copy2", copy_spy)
    source.write_text("Budget v2, much longer", encoding="utf-8")
    assert ingest.add_version(rig.conn, rig.vault, item_id, new_source=source, actor="system") == 2
    note = rig.vault.abs(_row(rig.conn, note_id)["path"])
    note.write_text(note.read_text(encoding="utf-8").replace("one", "two"), encoding="utf-8")
    assert ingest.add_version(rig.conn, rig.vault, note_id, new_source=None, actor="user") == 2
    assert {kind for kind, _ in in_transaction} == {"hash", "copy"}
    assert not any(inside for _, inside in in_transaction), in_transaction
    assert rig.vault.abs(_row(rig.conn, item_id)["path"]).read_text(encoding="utf-8") == "Budget v2, much longer"
    versions = rig.conn.execute("SELECT path FROM versions WHERE item_id = ? ORDER BY n", (note_id,)).fetchall()
    assert "two" in rig.vault.abs(versions[1]["path"]).read_text(encoding="utf-8")
    assert ingest.add_version(rig.conn, rig.vault, note_id, new_source=None, actor="user") is None  # unchanged
    assert not [p for p in rig.vault.version_dir(note_id).iterdir() if p.name.endswith(".part")]


def test_opendocument_files_finish_with_extraction_skipped(rig: Rig, tmp_path: Path) -> None:
    """Regression: .odt/.ods are typed document/spreadsheet but have no extractor, so they fell to the plain
    text reader, looked binary and failed the extract stage on every run (the item never finished)."""
    for name in ("letter.odt", "sheet.ods"):
        with zipfile.ZipFile(tmp_path / name, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("mimetype", "application/vnd.oasis.opendocument.text")
            archive.writestr("content.xml", os.urandom(4096))
        rig.import_path(tmp_path / name)
    rig.run()
    rows = rig.conn.execute("SELECT * FROM items").fetchall()
    assert len(rows) == 2
    for row in rows:
        stage = {s.stage: s for s in store.stages(rig.conn, row["id"])}["extract"]
        assert stage.status == "skipped" and "OpenDocument" in (stage.detail or ""), (row["path"], stage)
        assert row["pipeline_status"] == "done"
