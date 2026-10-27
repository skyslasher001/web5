# Phase 2: Vault + Recall

Status: **delivered 2026-10-13, approved 2026-10-13.** Phase 3 (agent engine) is delivered: [PHASE-3.md](PHASE-3.md).

Phase 2 makes UNIVERSE a place to keep things and find them again. You can drop in files or folders, capture a note from any app, and find anything by its name, the words inside it, or what it's about, in well under a second. Design decisions are in [ADR-0010](adr/0010-phase-2-vault-pipeline.md).

**Done when** (SPEC §25): *"I drop in 500 mixed files and find any of them by keyword or meaning in under a second."* `tests/integration/test_done_when.py` does exactly that, through the real pipeline and Core's search API:

| Measured (4-core Linux sandbox, fake embedder) | Result | Budget |
| --- | --- | --- |
| 500 mixed files found first by their own name | 500 / 500 | all |
| Meaning queries ("dog" → files about a puppy, no shared word) | top hit on topic, ≥ 9 of the top 10 on topic, for all 9 topics | — |
| Slowest search, request to response | 309 ms | < 1 s |
| Keyword search inside Core, p95 | 3 ms | < 100 ms |
| Hybrid search inside Core, p95 | 147 ms | < 400 ms |
| Ingest and full processing | ~4 files/s (OCR is ~80% of it) | — |
| List scrolling, 300+ items (Electron, software rendering) | 16.7 ms median frame (60 fps) | < 34 ms |

## What you can do now

**Get things in**
- **Drag and drop** files or whole folders anywhere on the window. They're copied into the vault (`<type>/<yyyy>/<mm>/`); your originals are never moved or changed. Duplicates are recognised by content hash.
- **Quick capture from any app:** press `Ctrl+Space` (changeable in Vault → Command bar), press `Tab`, type, and press `Ctrl+Enter`. `#hashtags` become tags. A lone URL becomes a link item.
- **Tray icon:** quick search, quick capture, and *Save clipboard to inbox* (text or an image).
- **Watched folders** (Vault panel → *Watch a folder…*): new and changed files are copied in automatically, with an optional default galaxy.
- **Local API** for scripts: create a key in Vault → Local API (shown once, stored hashed), then `POST /api/v1/capture` or `/api/v1/capture/files`, and `GET /api/v1/search`, with `Authorization: Bearer uk_…`. Keys have scopes (`capture`, `search`) and can't read arbitrary paths.

**Processing** (background workers, below-normal priority, paused on battery or while you chat):
- metadata (file info, EXIF, audio tags), text from PDF/DOCX/XLSX/PPTX/Markdown/code/CSV/HTML, OCR for images, thumbnails, captions with an Ollama vision model (only if you choose one), chunking, embeddings, and a sidecar `.universe.json` next to each file.
- Each item shows its stages, and why one failed or was skipped. *Reprocess* runs them again.
- Notes keep every version (`.universe/versions/<id>/<n>.md`), including edits you make on disk in another editor.

**Find things**
- **Search field** in the top bar (`/` to focus). Results come back as you type, with highlighted snippets. Words, fragments (`4471` in `parcel-4471`), scanned text in images, and meaning are all searched together.
- **The query understands filters:** `pdfs about the lake`, `photos from last summer`, `notes in DevMind`. What it understood shows as chips.
- **Command bar** (`Ctrl+Space` from any app): type, then `Enter` opens the best match or follows an intent (`open budget`, `go to music`, `show photos from may`). `Ctrl+Enter` shows the item in UNIVERSE instead.
- **Grid and List views** (`G`, `L`, back to the universe with `U`): type filters, sort, the trash, keyboard navigation (arrows, `Enter` to open, `Delete` to trash). Both scroll smoothly through tens of thousands of items.
- **Item panel:** preview, open, show in folder, pin, galaxies, tags, text, processing status, versions.

**Keep it safe**
- **Trash** for 30 days, then purged everywhere (file, versions, thumbnail, index entries, vectors). *Delete forever* does it at once.
- **Encrypted backups with restic** (Vault → Backups): pick an external drive or NAS folder. A strong password is generated and shown once, then kept in Windows Credential Manager. Backups run daily at 3:00 (or now, by hand), snapshot the databases safely, and can be verified (a real test restore) and restored into an empty folder. They never overwrite the live vault.
- Before a database migration, a copy of the database is taken automatically.

**Smoother UI** (from your request to make the UI much smoother)
- The 3D universe renders only when you're looking at it; behind the grid and list it's a still backdrop.
- Lists refresh in place during big imports, so they don't jump back to the top while you scroll.
- Bursts of activity merge into one line ("Added 37 items").
- Short, motion-safe transitions; thumbnails fade in.
- **Smooth mode:** if your display keeps dropping frames, UNIVERSE turns off the glass blur and renders the universe at 1×, and tells you. You can also switch it in System → Display.

## Setup

From [PHASE-1.md](PHASE-1.md#setup), then:

1. `uv sync` and `pnpm install` (new: LanceDB, RapidOCR, pypdf, python-docx/pptx, openpyxl, tinytag, watchdog, keyring; TanStack Virtual in the UI).
2. **Search by meaning:** `ollama pull nomic-embed-text` (or `qwen3-embedding`). Without an embedding model, search is keyword-only and the UI says so. Pick a model in System → Search models.
3. **Backups (optional):** `winget install restic.restic`, then Vault → Backups.
4. **Image captions (optional):** pull a vision model in Ollama and choose it in System → Search models → Image captions. Off by default: it's slow on a CPU.
5. **Your vault:** in development it lives in `.dev/vault`. Set `UNIVERSE_VAULT_DIR` to use a real folder. More workers: `UNIVERSE_WORKERS=2` (0–8).

## Demo script (≈5 minutes)

1. `pnpm dev`. The HUD boots as in Phase 1. Note the new search field and the Universe/Grid/List switch in the top bar.
2. **500 files:** `uv run python scripts/seed_vault.py generate C:\Temp\seed500`. Drag the `seed500` folder onto the window. The *Indexing N* chip counts down while the activity ribbon says *Added … items*.
3. **Find by name:** type `falcon0005` in the search field. Then `little room once pricing`: words inside files, with the match highlighted.
4. **Find by meaning:** with an embedding model installed, type `dog`. Files about a puppy come back (*by meaning too*), though none contains "dog".
5. **Filters:** `pdfs about invoices`. The chips show what was understood.
6. **Grid:** press `G`. Thumbnails for the photos. Arrow keys move, `Enter` opens with the default app, `Delete` trashes (undo from the trash view).
7. **Command bar from another app:** switch to any other window and press `Ctrl+Space`. Type `quarterly`, press `Ctrl+Enter`: UNIVERSE comes forward with the item selected.
8. **Quick capture:** `Ctrl+Space`, `Tab`, type `Call the accountant about the invoice #finance`, `Ctrl+Enter`. Search `accountant`: it's there, tagged.
9. **Watched folder:** Vault → *Watch a folder…*, pick a folder, save a new file into it. It appears within a few seconds.
10. **Backup:** Vault → Backups, choose a folder on another drive, save the shown password, *Set up backups*, then *Back up now* and *Verify*.
11. **Timing:** create a local API key (Vault → Local API, search scope) and run `uv run python scripts/seed_vault.py bench C:\Temp\seed500-manifest.json --key uk_…`. It searches for every file and prints *PASS: every file found in under a second*.

## Tests

| Suite | Count | New in Phase 2 |
| --- | --- | --- |
| pytest (`uv run pytest`) | 171: 170 passed here, 1 Windows-only skipped (includes the real-Ollama tests, which skip without an `ollama` binary) | vault basics, job queue, pipeline over every type, REST API (incl. a real uvicorn + worker process), governor, watched folders, vault self-watch, restic backup/verify/restore, search relevance, paging, the 500-file done-when |
| Vitest (`pnpm exec vitest run`) | 60 | command bar decisions, focus targets, clipboard capture, hotkey settings, vault path checks, item types, activity bursts, frame budget |
| Playwright Electron (`pnpm test:e2e`) | 10 | add files and find them by keyword and meaning, command bar find + capture, vault panel, smooth scrolling through 300+ items |

Everything passed locally (Linux, Python 3.12.13, Node 22): `ruff`, `ruff format`, `pyright`, `eslint`, `prettier`, `tsc`, the generated-types check, `pnpm build` and the e2e run (under `xvfb-run`).

### Bugs found and fixed while building Phase 2

Each has a regression test.

- The embed stage stayed *running* forever when embedding failed; it now shows *failed* with the reason.
- `GET /models` named a cached chat model while Ollama was unreachable.
- A manual backup after 3:00 was followed at once by a scheduled one, which made *Verify* and *Restore* report "busy". Any backup since today's slot now counts. (The test only failed after 3 a.m.)
- Search returned the nearest neighbours of every query as matches ("accountant" found everything). Meaning matches now need real similarity, and their snippet shows text instead of "shopping document".
- The item count showed the loaded page (200), not the total.
- The command palette's new "Search the vault for …" row outranked typed commands.
- The hidden command-bar window could be picked as "the first window"; it now loads after the main window.

## Known limitations

- **Not yet run on Windows.** CI still ends in `startup_failure` before any job runs (an Actions setting or billing on this private repo; see [PHASE-1.5.md](PHASE-1.5.md#known-limitations-still-open)). Untested there in particular: the global shortcut, the tray, Explorer reveal, restic paths and exclude patterns, and Credential Manager.
- **`Ctrl+Space` may clash** with an input-method switcher (Chinese/Japanese/Korean keyboards). The Vault panel shows when the shortcut couldn't be registered; pick another one there.
- **No real embedding model was available here.** Ollama's registry and Hugging Face are unreachable from the build environment, so meaning search is tested with a stand-in embedder and with the real Ollama server running a generated toy model. The relevance cutoff (positive similarity, within 0.25 of the best match) is model-agnostic but untuned for `nomic-embed-text` and `qwen3-embedding`; tune it with `scripts/seed_vault.py bench` on your PC.
- **Ingest throughput is CPU-bound by OCR** (about 4 files/s here, faster on a desktop CPU). Items are findable by name immediately; their content becomes searchable as processing finishes.
- **Deferred by design** (ADR-0010): audio/video transcription (Phase 7), image embeddings and the reranker (need a model-download path), summaries, auto-tags and links (Phases 3 and 9), placement in the universe (Phase 4). Large libraries are copied in, not indexed in place.
- **The `pre-universe` tag** still isn't on GitHub (the git proxy refuses tag pushes).

## What's next: Phase 3 (agents)

Approved 2026-10-13 and in progress. Phase 3 brings the agent engine and the specialists (Librarian first, which will use this vault). Useful from you now: fix the Actions setting so Windows CI runs, run the demo on your PC with `nomic-embed-text`, and tell me if `Ctrl+Space` works on your keyboard.
