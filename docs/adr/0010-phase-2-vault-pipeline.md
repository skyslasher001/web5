# 0010 — Phase 2 vault pipeline: workers under Core, Ollama embeddings, staged model roles

- Status: Accepted
- Date: 2026-10-13
- Flags: architecture, privacy

## Context

Phase 2 (SPEC §25) builds the vault, the ingestion pipeline, hybrid search, the command bar, watched folders and backups. ARCHITECTURE.md assumed three things that don't hold yet:

- The supervisor spawns the ingestion workers. The supervisor is protected core, so adding a service to it needs an owner-applied patch.
- An ONNX models service hosts the reranker, SigLIP image embeddings and OCR.
- faster-whisper transcribes audio.

The reranker, SigLIP and Whisper weights come from Hugging Face. There's no approved download path for them yet: the egress gate only allows loopback traffic, and there's no Model Manager. Hugging Face is also unreachable from the build environment, so none of these could be verified.

## Decision

1. **Workers are child processes of Core**, not of the supervisor.
   - Core starts N workers (default 1, `UNIVERSE_WORKERS`) as `python -m universe_vault.worker`. They run at background OS priority (`BELOW_NORMAL_PRIORITY_CLASS` / nice 10).
   - Core restarts a crashed worker with backoff.
   - Each worker exits by itself when Core disappears (the same parent watch as Core), and the supervisor's Job Object still contains them.
   - Jobs survive any crash through leases (ADR-0002).
   - Workers publish events through `POST /internal/events` with a per-boot internal token.
2. **Text embeddings come from Ollama** (`/api/embed`, router tier `embed_text`), which ARCHITECTURE.md already lists as an Ollama role.
   - Vectors go to LanceDB, one table per (model, digest).
   - Changing the embedding model re-queues the embed stage in the background. Search keeps working by keyword in the meantime.
3. **Pipeline stages in Phase 2:**
   - hash + dedupe
   - metadata (file, EXIF via Pillow, audio tags via tinytag)
   - text extraction (plain text, Markdown, code, CSV, JSON, HTML, PDF via pypdf, DOCX, XLSX, PPTX)
   - chunking
   - OCR for images (RapidOCR). Its PP-OCR models ship inside the wheel, so it runs offline.
   - captions via an Ollama vision model, when one is installed
   - thumbnails
   - text embeddings
   - sidecars
4. **Deferred stages, each with the phase that brings what it needs:**
   - Audio/video transcription → Phase 7 (STT service and its model download).
   - Image embeddings (SigLIP) and the cross-encoder reranker → when the models service and an audited model-download path exist. Until then, hybrid search is FTS5 BM25 + vectors, fused with reciprocal-rank fusion plus boosts. ARCHITECTURE.md already allowed "reranker skipped" for Lite.
   - Summary, auto-tags, entities and link suggestions → Phase 3 (Librarian, model broker) and Phase 9 (auto-linking).
   - Placement in the universe → Phase 4.
5. **Import copies into the vault.**
   - Dropped files, captures, API uploads and watched folders are copied to `<type>/<yyyy>/<mm>/`.
   - Sources are never moved or modified.
   - Indexing large libraries in place is deferred: deletion semantics for files outside the vault need their own design.
6. **Backups use restic as an external binary you install** (`winget install restic.restic`), like Ollama.
   - The SQLite databases are snapshotted with the SQLite backup API before each run, and the live files are excluded.
   - The repository password lives in the OS credential store.
   - A restore always goes to a separate folder, never over the live vault.
7. **A pre-migration copy of each database** is taken automatically before Core applies a new migration to a database that already has data (SPEC §18: "snapshots are mandatory before any … migration").

Verified for this decision (2026-10-13):

- lancedb 0.40.0 is Apache-2.0 and has a cp310-abi3 Windows wheel.
- pyarrow 26 is Apache-2.0.
- rapidocr 3.10.0 is Apache-2.0, bundles PP-OCRv6 models, and works with OpenCV 5.
- onnxruntime 1.31 is MIT.
- pypdf 6.20 is BSD-3. python-docx, openpyxl, python-pptx and tinytag are MIT. watchdog 6 is Apache-2.0. Pillow 12 is MIT-CMU. keyring 25.7 is MIT.
- restic 0.19 is BSD-2.
- strace showed **zero network connections** while LanceDB and RapidOCR ran.

## Consequences

- No supervisor change is needed for Phase 2. The supervisor still restarts Core, and Core restarts its workers.
- Semantic search needs an embedding model in Ollama (for example `ollama pull nomic-embed-text`). Without one, search is keyword-only and the UI says so.
- Photos are found by meaning through their OCR text and captions, not by pixels, until image embeddings land.
- Audio and video are found by filename and tags, not by what's said in them, until Phase 7.
- About 200 MB more on disk for the Python environment (LanceDB, Arrow, OpenCV, ONNX Runtime).

## Alternatives considered

- **Workers as supervisor services:** matches the original plan, but needs a protected-core patch for app code that Forge should be able to repair. It may still move there later, if the governor needs the supervisor to pause workers when Core is hung.
- **Pipeline in Core threads:** simpler, but CPU-heavy extraction and OCR would compete with request handling for the GIL, and a native crash would take Core down.
- **sqlite-vec instead of LanceDB:** smaller, but brute-force only. ADR-0003 chose LanceDB for on-disk ANN at 50k items, and it held up in the checks above.
- **Downloading reranker/SigLIP/Whisper weights now:** needs a non-loopback egress policy for huggingface.co plus a Model Manager, which is a privacy and security change in its own right. It can't be verified from this build environment either.
