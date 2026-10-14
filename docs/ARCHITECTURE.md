# UNIVERSE — Architecture (Phase 0 Blueprint)

Status: **Phase 0 approved 2026-10-12 · Phase 1 (Foundation) implemented, fixes in Phase 1.5** · Source of requirements: [`SPEC.md`](../SPEC.md)

This is the living architecture document. Forge keeps it current from Phase 5 on; every material change also gets an ADR in [`docs/adr/`](adr/).
It covers Phase 0 deliverables 1–7 (SPEC §27). Deliverables 8–9 (hardware info, questions) are in [`docs/PHASE-0.md`](PHASE-0.md). What Phase 1 actually built, and where it changed this design, is in [`docs/PHASE-1.md`](PHASE-1.md).

Contents

1. [Architecture](#1-architecture)
2. [Final tech decisions](#2-final-tech-decisions)
3. [Repo folder tree](#3-repo-folder-tree)
4. [Data model](#4-data-model)
5. [API and event outline](#5-api-and-event-outline)
6. [Universe UI concept](#6-universe-ui-concept)
7. [Forge safety design](#7-forge-safety-design)

---

## 1. Architecture

### 1.1 Diagram

```
┌─────────────────────────────── ELECTRON 44 · apps/desktop ────────────────────────────────┐
│ RENDERER (apps/ui) · sandboxed · contextIsolation · strict CSP · loaded from app://       │
│   React 19 · R3F universe · HUD · panels · viewers · 2D views                             │
│   mic capture + TTS playback in Chromium (WebRTC echo cancellation -> barge-in)           │
│                       ^ typed IPC (preload / contextBridge, no Node in renderer)          │
│ MAIN · windows · tray · global hotkeys · command-bar window · desktopCapturer · drag-drop │
│   [protected] kill switch · consent state + indicators · native approval dialog           │
└──────────────┬───────────────────────────────────────────────────────┬────────────────────┘
               │ REST + WS · 127.0.0.1:47821                           │ control API · 127.0.0.1:<random>
               │ session token · Host + Origin checks · WS tickets     │ supervisor token (main only)
               v                                                       v
┌──────────────────────────────────────┐   ┌──────── SUPERVISOR · stdlib-only Python [protected] ──┐
│ CORE · FastAPI                       │<──┤ spawns + health-checks every service, restarts with   │
│ API · WS hub · event bus             │   │ backoff · last-known-good · safe mode · applies and   │
│ orchestrator + agent runtime         │   │ rolls back approved Forge commits · state.json        │
│ recall / search · memory             │   └───┬──────────────┬──────────────────┬─────────────────┘
│ permissions · approvals · budget     │       │ spawns       │                  │
│ audit writer · governor · scheduler  │       v              v                  v
│ model router + broker · egress gate  │   ┌─ WORKERS xN ─┐ ┌─ VOICE ──────┐ ┌─ MODELS · ONNX RT ─┐
└───┬──────────────────────────────────┘   │ lease jobs   │ │ VAD · wake   │ │ reranker · SigLIP  │
    │ OpenAI-compatible HTTP               │ from SQLite, │ │ STT · TTS    │ │ OCR · hw detection │
    v                                      │ run pipeline │ │ WS audio     │ └────────────────────┘
┌─ OLLAMA :11434 (llama.cpp alt.) ─┐       │ stages       │ │ lazy start   │
│ LLMs · VLM · text embeddings     │       └──────────────┘ └──────────────┘
└──────────────────────────────────┘
┌───────────────────────────── DATA · vault root, outside the repo ─────────────────────────────────┐
│ <type>/<yyyy>/<mm>/...  originals · Markdown notes · *.universe.json sidecars (Obsidian-readable) │
│ .universe/universe.db   WAL · items · FTS5 · links · jobs · memories · tasks · approvals          │
│ .universe/events.db     persisted events (timeline)  ·  .universe/audit.db  append-only, chained  │
│ .universe/vectors/      LanceDB, one table per (kind, model)  ·  versions/ · thumbs/ · cache/     │
└───────────────────────────────────────────────────────────────────────────────────────────────────┘
App source: local git repo (Forge worktrees in .forge/) · Backups: restic -> external drive / NAS, encrypted
Optional sidecars (container runtime): SearXNG · code sandbox (no network) · capped cloud LLM via egress gate
```

Changes from the SPEC §4 sketch, and why:

- **Vision is not its own process.** Capture can only happen in Electron (desktopCapturer), the VLM runs in Ollama and OCR runs in the models service. A fourth process would only forward bytes. The `services/vision` package holds the logic and runs inside Core.
- **The models service is new.** Rerankers, SigLIP image embeddings and OCR are ONNX models that Ollama doesn't serve. They need one owner so the governor can load and unload them.
- **Mic capture and TTS playback live in the renderer.** That gives Chromium's built-in WebRTC echo cancellation for free, so barge-in works without a headset. Audio frames stream to the voice service over a WebSocket.
- **Code approvals bypass Core.** The final "apply" for a Forge patch travels renderer → native dialog in Electron main → supervisor. Core and the renderer are both code Forge can patch, so neither can apply a change on its own (§7).

### 1.2 Processes

| Process | Language | Started by | Restart policy | Notes |
| --- | --- | --- | --- | --- |
| Electron main | TS | user / login item | — | Owns windows, tray, hotkeys, consent state, kill switch. Launches the supervisor and restarts it if it dies. |
| Renderer | TS/React | Electron main | reload on crash | Never talks to the OS directly. Typed IPC only. |
| Supervisor | Python 3.12 stdlib only | Electron main | restarted by main | Imports nothing from the app venv, so a broken dependency upgrade can't break it. Holds child processes in a Windows Job Object so nothing is orphaned. |
| Core | Python (FastAPI/uvicorn) | supervisor | backoff 0.5 s → 30 s | Single process. Agents run here as asyncio tasks. All request handlers are `async`, so app state is only touched on the event loop. Exits by itself if its parent process disappears, so it can never be left holding its port. |
| Workers ×N | Python | supervisor | backoff | N = governor-controlled (default 2). Background priority (`BELOW_NORMAL_PRIORITY_CLASS`). Started lazily when jobs exist. |
| Voice | Python | supervisor | backoff | Started only when the mic is turned on. STT + VAD + wake word + TTS. |
| Models | Python (ONNX Runtime) | supervisor | backoff | Lazy-loads each model on first use. Evicted under VRAM pressure. |
| Ollama | Go (external) | supervisor (or reuses a running instance) | backoff | `OLLAMA_HOST=127.0.0.1`. The model directory is user-chosen. |
| Sidecars | containers | supervisor (on demand) | backoff | SearXNG, code sandbox. Optional. |

### 1.3 Trust boundaries

1. **Renderer ↔ main:** contextIsolation, `sandbox: true`, no `nodeIntegration`. The preload exposes a fixed, typed API. The renderer can *request* consent changes but only main can *change* them, and main owns the indicators.
2. **UI/main ↔ Core:** loopback only. A per-session bearer token is generated by the supervisor at boot and given to main, which hands it to the preload. WebSockets authenticate with short-lived single-use tickets because browsers can't set WS headers. Every request must carry `Host: 127.0.0.1:<port>` (DNS-rebinding defence), and any `Origin` must be allowlisted (`app://universe`, plus the Vite dev origin in dev). CORS is enabled for exactly those origins, since the renderer is a different origin from Core; everything else is refused before routing (ADR-0006).
3. **External scripts ↔ Core (local API):** separate API keys, scoped (`capture`, `search`), shown once, stored hashed, revocable. The keys live in Windows Credential Manager on the client side.
4. **Core ↔ the internet:** every outbound request goes through the **egress gate**, the one module allowed to open sockets. It enforces the offline switch, per-agent domain rules and the kill switch, and audit-logs every request. Lint plus a unit test ban direct `httpx`/`requests`/`urllib` use anywhere else. Optional hard enforcement comes from Windows Firewall rules for the app's executables (Phase 12).
5. **Agents ↔ tools:** a policy engine checks every tool call (§7.3 and §5.4).
6. **Forge ↔ the code:** Forge works in worktrees and can only *propose*. Only the supervisor applies, and only after a native-dialog approval (§7).

### 1.4 Key flows (with latency budgets)

**Recall, fast path** ("go to Ember Wolf", target < 300 ms after the transcript arrives):
`command bar / STT final` → `POST /recall` → intent grammar (verbs: open, go to, show, play, pin, find; slots resolved with FTS5 over titles, projects and entities, dates parsed with dateparser plus season/part-of-day rules) → if confidence ≥ 0.85, return `{action: fly_to, target}` (≈ 20–60 ms) → the renderer flies the camera. No LLM call.

**Recall, hybrid** (target < 400 ms): run FTS5 BM25 (top 100) and the LanceDB ANN query (query embedding ≈ 20–80 ms) in parallel. Fuse them with reciprocal-rank fusion, boost (recency, opens, pinned, current project, graph distance), then rerank the top 30–50 (cross-encoder, GPU) → constellation results. On CPU-only hardware the reranker drops to the top 20 or is skipped (Lite). Budgets are measured in Phase 2 with the seed generator: on 500 mixed files, keyword p95 3 ms and hybrid p95 147 ms inside Core, slowest request 309 ms ([PHASE-2.md](PHASE-2.md)). Phase 2 runs without the reranker (ADR-0010).

**Chat, smart path** (first token < 1 s): `chat.send` over WS → the orchestrator retrieves context (the same hybrid search, items cited by id) → the model broker sends the request at *realtime* priority → tokens stream back as `chat.token` events → the final message carries `citations[]`.

**Ingestion:** drop / watch / capture / API → `item.created` (status `inbox`) → the pipeline DAG is enqueued as jobs (`hash → metadata → extract → {ocr | transcribe | caption+image-embed} → text-embed → summary → tags → entities → links → place`) → workers lease jobs only when the governor says background work may run → each stage writes `item_stages` and emits `pipeline.stage.*` → failures retry with exponential backoff, then go `dead` and are reported to Forge. *Phase 2 as built (ADR-0010):* workers are child processes of Core, not supervisor services; one `pipeline` job runs metadata → extract → thumbnail → OCR, then enqueues `caption` (only with a chosen vision model) and `embed`, which also writes the sidecar. Stages chain by enqueueing the next job. Transcription, image embeddings, summary, tags, entities, links and placement come in later phases.

**Kill switch:** hotkey, tray or HUD → Electron main (protected code) *first* stops mic, screen and camera capture locally (no backend round trip), *then* calls the supervisor `POST /killswitch`. The supervisor tells Core to cancel all agent tasks and close the egress gate, pauses workers and stops voice. If Core doesn't ack within 1 s, the supervisor hard-kills it and restarts it with agents disabled. The kill switch works even when Core is hung.

### 1.5 Performance governor

- **Priority classes:** `realtime` (voice, active chat, UI requests) > `interactive` (search, vision, Navigator) > `background` (pipeline, consolidation, Forge verification).
- **Model broker (in Core):** every LLM/VLM/embedding call goes through one priority queue with per-class concurrency limits. While voice or chat is active, background LLM concurrency drops to 0. Ollama has no priority scheduling of its own, so this queue provides it.
- **VRAM manager:** reads NVML (NVIDIA) or Windows GPU performance counters (AMD/Intel) and keeps the hot model resident (`keep_alive`). A background model may only load when headroom ≥ its size + margin.
- **Yield:** background work pauses when any of these hold: a fullscreen or exclusive app is in the foreground (`SHQueryUserNotificationState`), the PC is on battery, CPU > 70 % or GPU > 60 % for 10 s outside our processes, or the user is active in the 3D view and FPS is under budget. It resumes after 60 s idle.
- **Idle scheduler:** consolidation, re-embedding and Forge benchmarks need ≥ 10 min of user idle (`GetLastInputInfo`) and AC power.

---

## 2. Final tech decisions

Versions are the current releases on npm / PyPI as of **2026-10-12**; licenses come from the package metadata. **Δ** = a change from the SPEC §22 default (each has an ADR). **⚠** = a license flag, with the alternative in §2.2. Everything is pinned in lockfiles in Phase 1 (`pnpm-lock.yaml`, `uv.lock`).

### 2.1 Stack

| Layer | Decision | Why (one line) | License |
| --- | --- | --- | --- |
| Desktop shell | **Electron 44** + electron-builder 26 / electron-updater 6 (installer: Phase 12). Chromium background traffic disabled ([ADR-0009](adr/0009-electron-privacy-hardening.md)) | Chromium everywhere means WebGL/WebGPU parity, WebRTC echo cancellation and desktopCapturer, plus the same stack as DevMind for reuse. Tauri's RAM saving doesn't matter against a 1 GB idle budget. ([ADR-0001](adr/0001-process-model-and-supervisor.md)) | MIT |
| Frontend | **React 19.3 + TypeScript 6.0 + Vite 8** | TS pinned to 6.0 because typescript-eslint 8.71 supports `<6.1`. Move to TS 7 (native compiler) when lint tooling catches up. ([ADR-0007](adr/0007-runtime-pins.md)) | MIT / Apache-2.0 / MIT |
| 3D universe | three 0.186, @react-three/fiber 9.8 · Lite: sigma 3.0.3 + graphology 0.26 · Graph layout: d3-force-3d 3.0.6 | *Phase 4 as built (ADR-0012):* one `THREE.Points` draw with procedural shapes per type, size-based LOD and GPU picking cover 50k items; layouts run in a Web Worker; bloom from three's own `UnrealBloomPass` (no drei/postprocessing). Labels are a DOM overlay, not extra React roots. | MIT |
| 2D Lite graph | **sigma 4 + graphology** | WebGL 2D graph built for large node counts. Chosen over force-graph because rendering and layout are separate (layout runs in a worker). | MIT |
| UI kit | Radix primitives, Tailwind 4.3, Motion 14, cmdk 1.1, lucide-react icons | Accessible primitives. Tailwind v4 themes from CSS variables generated from the design tokens. | MIT / MIT / MIT / MIT / ISC |
| UI state & data | Zustand 5, TanStack Query 5, TanStack Virtual 3 | Small stores. Server cache, invalidated by WS events. Virtualized lists everywhere. | MIT |
| Editors & viewers | CodeMirror 6 (Markdown + code), pdf.js, wavesurfer.js 8, Leaflet 1.9 | Mature and offline. One editor engine for notes and code. | MIT / Apache-2.0 / BSD-3 / BSD-2 |
| Fonts | Space Grotesk (UI headings), Inter (UI text), JetBrains Mono (data/code), bundled via @fontsource | Offline. No Google Fonts calls. | OFL-1.1 |
| Backend | **Python 3.12**, FastAPI 0.143, uvicorn 0.54, Pydantic 2.14 | 3.12 because kokoro 0.9.4/misaki require `<3.13`. Every other dependency ships cp312 Windows wheels (checked). | PSF / MIT / BSD-3 / MIT |
| Python env | uv 0.13 (workspace; uv-managed Python, so no system Python needed) | One lockfile, fast installs, reproducible. | MIT / Apache-2.0 |
| JS workspace | pnpm 12 workspaces, Node 24 LTS for tooling | Strict, fast monorepo installs. Electron bundles its own Node at runtime. | MIT |
| DB access | **stdlib `sqlite3`, hand-written SQL, versioned up/down SQL migrations** (no ORM) **Δ** | FTS5, triggers and WAL tuning are SQLite-specific. An ORM adds weight, not safety. ([ADR-0003](adr/0003-storage-layout.md)) | Public domain |
| Database | SQLite (WAL) + FTS5, split into `universe.db` / `events.db` / `audit.db` | Splitting isolates hot event writes and lets the audit DB be append-only and protected. | Public domain |
| Vectors | **LanceDB 0.40** (embedded) | Disk-based ANN indexes (IVF-PQ/HNSW) and metadata prefilters, no server. One table per (kind, model) makes re-embedding a background swap. | Apache-2.0 |
| Job queue | **Custom SQLite `jobs` table with leases** (instead of huey) **Δ** | We need a per-item stage DAG, priority classes the governor can pause, leases that survive crashes and progress events. Bending huey to that costs more than ~300 lines. ([ADR-0002](adr/0002-sqlite-job-queue.md)) | — |
| Scheduling | croniter (cron triggers, inside Core's scheduler loop) | Tiny. No APScheduler daemon semantics needed. | MIT |
| File watching | watchdog 6 | Native ReadDirectoryChangesW on Windows. | Apache-2.0 |
| Agent loop | **Custom loop** on the OpenAI-compatible API + Pydantic tool schemas + a minimal stdio MCP client of our own (the `mcp` SDK is a dev-only test dependency, ADR-0011) **Δ (picked from the two SPEC options)** | Permissions, hours-long approval pauses, taint tracking, budget stops, kill switch and audit are the safety model and must be our code. The rest is ~400 lines. ([ADR-0004](adr/0004-custom-agent-loop.md)) | MIT |
| LLM client | **Thin OpenAI-compatible streaming client** (~60 lines) over the egress gate's httpx client **Δ (Phase 1)** | One interface for every provider (SPEC §15), one less dependency, every call gated. ([ADR-0005](adr/0005-model-runtimes.md)) | BSD-3 (httpx) |
| LLM / VLM runtime | **Ollama** (primary) · llama.cpp `llama-server` (alternative plugin) | Native Windows, GPU auto-detect, model pulls, `keep_alive` residency, OpenAI-compatible. llama.cpp for finer control (e.g. MoE expert offload). ([ADR-0005](adr/0005-model-runtimes.md)) | MIT / MIT |
| ONNX models | **ONNX Runtime 1.31** (CUDA EP on NVIDIA; DirectML EP on AMD/Intel; CPU fallback) | One runtime for reranker, SigLIP and OCR models, with no PyTorch in the hot path. | MIT |
| Embeddings / reranker / VLM / LLM models | Candidate shortlist per hardware tier in §2.3. Final picks come from local benchmarks in Phase 1–2. | SPEC §15: don't hardcode from memory. | Apache-2.0 / MIT only (flags in §2.2) |
| STT | faster-whisper 1.2 (CTranslate2 4.8) + Silero VAD 6 | Streaming-capable, int8/fp16 on GPU, good CPU fallback. Parakeet / Granite Speech benchmarked as candidates in Phase 7. | MIT |
| Wake word | openWakeWord runtime (ONNX), **custom-trained "Hey Universe"** | Apache-2.0 runtime. Pretrained models are non-commercial so they aren't shipped. ⚠ Training-data licensing is checked before training (§2.2). | Apache-2.0 |
| TTS | **Kokoro-82M** via `kokoro-onnx` | Best quality per CPU-millisecond among permissive models. Multiple voices give each agent its own. ⚠ espeak-ng fallback (§2.2). | Apache-2.0 weights / MIT runtime |
| OCR | **RapidOCR 3.10** (PP-OCRv5 models on ONNX Runtime) · Tesseract fallback **Δ** | Same PaddleOCR models without the PaddlePaddle framework. Much lighter install on Windows. | Apache-2.0 |
| Doc extraction | pypdf 6 (fast path), pdfplumber (tables), docling 2 (deep layout, opt-in background), python-docx, openpyxl | Permissive. PyMuPDF (AGPL) avoided. | BSD-3 / MIT / MIT / MIT / MIT |
| Audio metadata | **tinytag** (instead of mutagen) **Δ** | mutagen is GPL-2.0+. tinytag (MIT) reads ID3/MP4/FLAC/OGG/WAV tags. | MIT |
| Media decode | PyAV 19 (bundled LGPL FFmpeg) · LGPL FFmpeg build as a separate binary | Audio from video for transcription, plus thumbnails. LGPL is fine when dynamically linked or run as a separate process. | BSD-3 / LGPL-2.1+ |
| Images | Pillow 12, ImageHash 4 (pHash dedupe), pillow-heif (HEIC) ⚠ | Standard stack. iPhone HEIC needs libheif (§2.2). | MIT-CMU / BSD-2 / BSD-3 |
| Semantic layout | **numpy** in the vault worker process (random projection → PCA → k-means → cluster-centre PCA to 3D), cached in `layout_cache` **Δ** | *Phase 4 as built (ADR-0012):* 50k in ≈14 s with no new dependency; umap-learn (≈200 MB native deps, minutes per layout) can replace it behind the same `/layout/semantic` endpoint if clustering is poor. | BSD-3 |
| Audio analysis (Phase 10) | librosa 1.0, Demucs 4, basic-pitch 0.4 | Per SPEC. | ISC / MIT / Apache-2.0 |
| Web search / fetch (Phase 6) | SearXNG (container, unmodified) ⚠ · trafilatura 2.3 · Playwright 1.63 · ddgs fallback | SearXNG is AGPL but runs unmodified as a separate service, so no copyleft reaches our code. | AGPL-3.0 / Apache-2.0 / Apache-2.0 / MIT |
| Sandbox & sidecars | **Podman on WSL2** (default) or Docker Desktop: rootless containers, `--network none`, read-only bind mounts | The only real isolation on Windows Home. Choice pending (Question 3). | Apache-2.0 (Podman) |
| Secrets | keyring 25 → Windows Credential Manager | Per SPEC. Nothing secret in config or logs. | MIT |
| Backups | restic (encrypted, deduplicated, versioned) | Per SPEC. The repo password lives in Credential Manager. | BSD-2 |
| Logging / metrics | structlog 26 (JSON, rotating per service) · psutil 7 · nvidia-ml-py | Structured logs Forge can parse. Vitals with no Prometheus stack. | MIT-or-Apache / BSD-3 / BSD |
| Hardware detection | psutil + nvidia-ml-py + Electron `app.getGPUInfo` + DXGI adapter memory (via a PowerShell/WMI fallback) | Win32_VideoController caps VRAM at 4 GB, so DXGI/registry is needed for the real figure. | — |
| Testing | pytest 9, Vitest 5, Playwright 1.64 (`_electron`), pytest-benchmark | Per SPEC. Playwright drives the real Electron app. | MIT / MIT / Apache-2.0 / BSD-2 |
| Lint / format / types | ruff 0.17 (lint + format), **pyright** (over mypy), ESLint 10 + typescript-eslint, Prettier 3, `tsc --noEmit` · pre-commit 4 | pyright is faster and matches the TS editor experience. One type checker is enough. | MIT |
| Shared types | Pydantic → OpenAPI → `openapi-typescript`. Event payloads → JSON Schema → TS | The backend is the source of truth. The UI can't drift. | MIT |
| CI | GitHub Actions on `windows-latest` + `ubuntu-latest` | Windows-specific code gets tested on Windows on every push. | — |

### 2.2 License flags

Policy (strict by default): treat UNIVERSE as distributable. Ship only MIT / Apache-2.0 / BSD / ISC / Zlib / OFL / MPL code and weights. Every flagged item below is either avoided or isolated, and the alternative is named.

| ⚠ Component | License issue | Decision / alternative |
| --- | --- | --- |
| espeak-ng (pulled in by Kokoro's G2P for out-of-vocabulary words, and bundled by `kokoro-onnx` via espeakng-loader) | GPL-3.0 | **Default:** espeak fallback *disabled*. Unknown words go through misaki's rule-based fallback (slightly worse pronunciation of rare words). **Option:** run espeak-ng as a separate process (aggregation, not linking). Fine for private use; recheck before any distribution. |
| Piper TTS (`piper-tts` 1.8 on PyPI = OHF-Voice fork) | GPL-3.0-or-later | **Not used.** Kokoro instead. The original MIT `rhasspy/piper` is archived. |
| openWakeWord *pretrained* models | CC BY-NC-SA 4.0 (non-commercial) | **Not shipped.** Train a custom "Hey Universe" model (Phase 7). Some of openWakeWord's negative-training datasets carry NC terms, so I verify the data licenses before training. Alternative: `livekit-wakeword` (reported Apache-2.0, synthetic-data training, ONNX output compatible with openWakeWord; license to be confirmed from its repo). |
| SearXNG | AGPL-3.0 | Run **unmodified** as a separate container, talked to over HTTP. No AGPL code in our tree. Fallback: free-tier search APIs + `ddgs` (MIT). |
| FFmpeg | LGPL-2.1+ (GPL if built with x264/x265) | Use **LGPL builds only** (PyAV wheels; separate `ffmpeg.exe` from an LGPL build). Never link GPL builds. |
| pillow-heif wheels | Bundle libheif/libde265 (LGPL); some builds include x265 (GPL) | Verify wheel contents in Phase 2. Alternative: decode HEIC through the Windows HEIF codec (WIC) or an LGPL FFmpeg. |
| mutagen | GPL-2.0+ | **Not used.** tinytag (MIT). |
| PyMuPDF | AGPL-3.0 | **Not used** (SPEC). pypdf + pdfplumber + docling. |
| docling model weights (layout/table models) | Model license separate from the MIT code | Verify the model card in Phase 2. If not permissive, docling stays opt-in and pypdf/pdfplumber are the default. |
| EmbeddingGemma, older Gemma ≤ 3 models | Gemma Terms of Use (not OSI) | Not in the default loadout. Gemma 4 is reported as Apache-2.0 (April 2026) and is a candidate *after* the model card is verified. |
| Llama-family models | Llama community license (use restrictions) | Not in the default loadout. |
| Parakeet / Canary STT weights | CC-BY-4.0 (permissive, attribution required) | Allowed with attribution in About → Licenses. Candidate only. |
| Docker Desktop (if chosen over Podman) | Proprietary. Free for personal use and small businesses (< 250 employees and < $10M revenue) | Default is Podman (Apache-2.0). See Question 3. |
| Music-generation models (Phase 10) | Mostly non-commercial | Flagged per model when we get there. Off by default. |

### 2.3 Model shortlist per hardware tier

**Caveat:** Hugging Face and ollama.com were blocked by this build environment's network policy, so the shortlist comes from web search on 2026-10-12, not from model cards. Phase 1 hardware detection plus the Model Manager re-verify every card (license, size, Windows/Ollama availability) and benchmark locally before anything becomes a default. Nothing here is hardcoded. Assignments live in `model_assignments` and are changed from the UI.

| Role (router tier) | CPU-only (≥ 16 GB RAM) | ≤ 8 GB VRAM | 12–16 GB VRAM | 24 GB+ VRAM |
| --- | --- | --- | --- | --- |
| `local-fast` LLM | Gemma 4 E2B | Gemma 4 E4B | Gemma 4 E4B | Gemma 4 E4B / Qwen3.6-35B-A3B (if fast enough) |
| `local-large` LLM | Gemma 4 E4B | Qwen3-VL-8B (doubles as vision) | gpt-oss-20b · Gemma 4 26B-A4B (MoE with CPU expert offload) | Qwen3.8-27B (dense, vision-capable) · Qwen3.6-35B-A3B |
| `vision` VLM | Gemma 4 E2B (if vision-capable) + OCR | Qwen3-VL-4B | Qwen3-VL-8B | Qwen3.8-27B |
| `embed_text` | nomic-embed-text v1.5 (137M) | Qwen3-Embedding-0.6B (512-d MRL) | Qwen3-Embedding-0.6B (1024-d) | Qwen3-Embedding-0.6B (4B only if the benchmark justifies it) |
| `rerank` | bge-reranker-v2-m3 int8, top-20 (or off) | bge-reranker-v2-m3 | bge-reranker-v2-m3 vs Qwen3-Reranker-0.6B | Qwen3-Reranker-4B candidate |
| `embed_image` | SigLIP 2 base/16 | SigLIP 2 base/16 | SigLIP 2 so400m | SigLIP 2 so400m |
| `stt` | faster-whisper small.en int8 · Parakeet-TDT-0.6B-v3 candidate | large-v3-turbo int8_float16 | large-v3-turbo | large-v3-turbo · Granite Speech / Canary candidates |
| `tts` | Kokoro-82M | Kokoro-82M | Kokoro-82M | Kokoro-82M |
| `ocr` | RapidOCR PP-OCRv5 | ← | ← | ← |
| `cloud` | off (opt-in per agent, hard monthly cap) | ← | ← | ← |

Licenses of the shortlisted families as reported: Qwen 3.x open weights Apache-2.0 (the Qwen3.8 flagship and "Flash" builds are *not*, and are excluded), Gemma 4 Apache-2.0, gpt-oss Apache-2.0, nomic-embed v1.5 Apache-2.0, bge-* MIT/Apache-2.0, SigLIP 2 Apache-2.0, Whisper MIT, Kokoro Apache-2.0.

---

## 3. Repo folder tree

This repo (`web5`) is the monorepo root (Phase 1). The Bolt landing page was removed (tag `pre-universe`). Directories for later phases (`voice/`, `vision/`, `research/`, `forge/`, `sentinel/`, `skills/`, `plugins/`, `evals/`) are created when their phase starts.

```
.                                  # repo root (product name: UNIVERSE)
├─ apps/
│  ├─ desktop/                     # Electron main + preload (TypeScript)
│  │  └─ src/
│  │     ├─ main/                  # windows, tray, hotkeys, command-bar window, capture, IPC
│  │     │  └─ protected/          # [protected] kill switch, consent state, native approval dialog, supervisor client
│  │     ├─ preload/               # typed contextBridge API (the only renderer → OS path)
│  │     └─ safe-mode/             # [protected] static safe-mode page (no React, no backend needed)
│  └─ ui/                          # React renderer
│     └─ src/
│        ├─ universe/              # R3F scene, celestial objects, layouts, LOD, GPU picking, camera
│        ├─ hud/                   # search bar, voice orb, agent dock, status cluster, approvals tray, ribbon
│        ├─ panels/                # context panel, chat, settings, model manager, vitals, privacy, audit
│        ├─ viewers/               # note, song, photo, pdf, code, video, project
│        ├─ views2d/               # grid, list, table, timeline, kanban, map
│        ├─ command/               # cmdk palette + command registry (every action is a command)
│        ├─ api/                   # typed REST/WS client, TanStack Query hooks, event subscriptions
│        ├─ state/                 # Zustand stores
│        └─ workers/               # web workers: layout, LOD bucketing
├─ services/                       # Python uv workspace (one venv; each dir is a package)
│  ├─ common/                      # config, ids (UUIDv7), logging, error capture, egress gate, sqlite helpers
│  ├─ core/                        # FastAPI app, WS hub, event bus, orchestrator, recall, memory, governor, scheduler
│  │  └─ protected/                # [protected] permissions/policy engine, consent API, audit writer, budget caps, kill switch handler
│  ├─ agents/                      # agent runtime (loop), tool registry, built-in tools, MCP client, model router + broker
│  ├─ vault/                       # storage layout, sidecars, versions, ingestion pipeline stages, jobs + workers, search
│  ├─ models/                      # ONNX model service (reranker, SigLIP, OCR), hardware detection, Ollama manager
│  ├─ voice/                       # VAD, wake word, STT, TTS, WS audio protocol
│  ├─ vision/                      # capture handling, VLM prompting, OCR fallback, watch mode (runs inside core)
│  ├─ research/                    # search providers, fetch/extract, cache, watchlists (Phase 6)
│  ├─ forge/                       # error triage, worktrees, repro, verification runner, proposals (Phase 5)
│  ├─ sentinel/                    # [protected] deterministic safety checks, backup + restore tests, health, budget watch
│  └─ supervisor/                  # [protected] stdlib-only watchdog, LKG, safe mode, apply/rollback
├─ agents/                         # <id>.yaml agent definitions + prompts/<id>.md (hot-reloaded)
│                                  #   forge.yaml and sentinel.yaml are [protected]
├─ skills/                         # approved learned skills: <name>/skill.yaml + steps + tests
├─ plugins/                        # provider plugins, each with manifest.yaml (llm/, embed/, rerank/, stt/, tts/,
│                                  #   wake/, vlm/, ocr/, search/, importers/)
├─ packages/
│  ├─ design-tokens/               # tokens.json (DTCG) → CSS vars, TS constants, Tailwind @theme, 3D palette
│  └─ shared-types/                # generated OpenAPI TS types + event JSON Schemas
├─ evals/                          # golden tasks per agent (<agent>/*.yaml) + scorers
├─ tests/
│  ├─ unit/  integration/  e2e/  perf/
│  └─ protected/                   # [protected] tests guarding the protected core and Forge limits
├─ docs/
│  ├─ ARCHITECTURE.md  PHASE-0.md
│  ├─ adr/                         # NNNN-title.md
│  └─ guides/                      # user guide, agent-authoring guide, plugin guide
├─ scripts/                        # dev.mjs (one-command start), seed.py, bench/, hardware-report.ps1, restore-lkg.ps1
├─ protected-core.txt              # [protected] glob manifest of paths Forge may never modify
├─ SPEC.md  AGENTS.md  CLAUDE.md  README.md  .env.example
├─ package.json  pnpm-workspace.yaml  pnpm-lock.yaml
├─ pyproject.toml  uv.lock  .python-version
├─ .pre-commit-config.yaml
└─ .github/workflows/ci.yml        # windows-latest + ubuntu-latest: lint, types, tests
```

Outside the repo:

```
%LOCALAPPDATA%\Universe\           # app runtime data (not user data)
├─ config.json                     # vault path, ports, first-run choices (no secrets)
├─ logs\<service>.jsonl            # rotated structured logs
├─ supervisor\state.json           # releases, LKG pointer, boot-failure counter, safe-mode flag
└─ runtime\                        # (installed builds) app checkout Forge patches; LKG worktree

<VaultRoot>\  (e.g. D:\UniverseVault\) — your data, see §4.5
```

One-command dev start (Phase 1): `pnpm dev` runs `uv sync` and starts Vite, then Electron. Electron main launches the supervisor, which brings up Core, the models service and Ollama. That's the same path as production, so dev exercises the supervisor.

---

## 4. Data model

Conventions: ids are **UUIDv7** stored as TEXT (time-sortable, generated anywhere). Timestamps are ISO-8601 UTC TEXT. JSON columns use SQLite JSON functions. Every table has `created_at` (and `updated_at` where mutable). `actor` values are `user`, `agent:<id>`, `system`, `external:<api-key-id>`.

### 4.1 `universe.db` (WAL)

Phase 1 implements `projects`, `conversations`, `messages` (plus `model`, `status`, `first_token_ms`, `total_ms`), `errors` and `settings` as migration 0001. The other tables arrive as numbered migrations in the phase that needs them.

| Table | Key fields | Notes |
| --- | --- | --- |
| `items` | id, type, title, slug, status (`inbox`/`triaged`/`active`/`archived`), idea_stage (`nebula`/`protostar`/`star`/`promoted`, ideas only), path (relative to vault root), mime, size_bytes, content_hash (sha256), current_version, captured_at (when it happened: EXIF/ID3/mtime), summary, metadata JSON, lat, lon, pinned, open_count, last_opened_at, source_id, trashed_at | `type` ∈ note, idea, song, audio, voice_memo, photo, video, document, pdf, spreadsheet, code_repo, code_file, link, screenshot, transcript, folder. Unique index on content_hash (dedupe). Indexes on (type, captured_at), (status), (last_opened_at). |
| `versions` | id, item_id, n, path, content_hash, size_bytes, created_by (actor), note | v1 is the original at `items.path`. Later versions live in `.universe/versions/<item_id>/<n>.<ext>`. Originals are never overwritten. |
| `item_stages` | item_id, stage, status (`pending`/`running`/`done`/`failed`/`skipped`), model, model_version, attempts, error, updated_at | Pipeline status per item. A model upgrade re-queues stages whose `model_version` is stale. |
| `chunks` | id, item_id, version_id, ord, text, page, start_ms, end_ms, char_start, char_end, token_count | Retrieval units (paragraphs, transcript segments, OCR blocks). |
| `chunks_fts` | FTS5(text), content=`chunks` | `unicode61 remove_diacritics 2` tokenizer. BM25 ranking. |
| `items_fts` | FTS5(title, summary, tags, entities), content-less, kept in sync by triggers | Title/metadata search for the fast path. Plus a `trigram` FTS5 table on titles for typo tolerance. |
| `links` | id, src_item_id, dst_item_id, dst_project_id, type (`related`/`references`/`derived_from`/`mentions`/`same_entity`/`inspired_by`/`part_of`), weight 0–1, state (`suggested`/`confirmed`/`rejected`), confidence, reason, created_by, confirmed_at | Rejected links are kept so they're never re-suggested. Exactly one of dst_item_id / dst_project_id is set. |
| `projects` | id, name, slug, description, status (`active`/`paused`/`done`/`archived`), color_token, layout_seed, goals JSON, origin_idea_id | Seeded with the 4 galaxies (SPEC §28). `origin_idea_id` records an idea promoted into a project. |
| `project_tasks` | id, project_id, title, status, due_at, ord, created_by | Your tasks (not agent tasks). Strategist writes here with approval. |
| `item_projects` | item_id, project_id, added_by, added_at | Many-to-many. Membership lives here, not in folders. |
| `tags` / `item_tags` | tags: id, name (unique NOCASE), color_token · item_tags: item_id, tag_id, state (`suggested`/`confirmed`), source (actor), confidence | Agent tags stay `suggested` until confirmed (or auto-confirmed by a rule you set). |
| `collections` / `collection_items` | collections: id, name, kind (`manual`/`smart`), query JSON · collection_items: collection_id, item_id, ord | Smart collections are saved searches. |
| `entities` / `item_entities` | entities: id, kind (`person`/`place`/`org`/`date`/`event`), name, canonical, data JSON · item_entities: item_id, entity_id, mentions, confidence | Pipeline step 10. Powers "photos with Sam" and "notes about Austin". |
| `sources` | id, kind (`drop`/`watched_folder`/`quick_capture`/`clipboard`/`api`/`importer`/`agent`/`web`/`screen`), origin (path/url/app), importer, api_key_id, agent_id, extra JSON | Provenance for every item. |
| `captures` | id, kind (`screen`/`window`/`region`/`camera`/`clipboard`/`voice_memo`), started_at, ended_at, trigger (`toggle`/`look_at_this`/`watch_mode`), app_name, window_title, saved_item_id | Metadata only. Pixels/audio are kept only if you said "save this" (then `saved_item_id` is set). Feeds the privacy dashboard. |
| `watched_folders` | id, path, recursive, include_globs, exclude_globs, default_project_id, enabled | |
| `agents` | id, name, version (sha of YAML), enabled, config JSON (resolved), source_path, updated_at | A mirror of `agents/*.yaml` for joins. The YAML is the source of truth. |
| `agent_tasks` | id, parent_id, conversation_id, agent_id, title, input, status (`queued`/`running`/`waiting_approval`/`done`/`failed`/`cancelled`), progress, steps_used, tokens_in, tokens_out, cost_usd, model, tainted (bool), correlation_id, error, started_at, finished_at | The task board. `tainted` = untrusted content entered the context (§7.3). |
| `task_steps` | id, task_id, n, kind (`llm_call`/`tool_call`/`tool_result`/`delegate`/`message`/`review`), model, tool, args JSON, result_ref, tokens, cost_usd, duration_ms | Agent traces. Large prompts/results are stored as files under `.universe/traces/` and referenced. |
| `approvals` | id, kind (`tool_call`/`forge_patch`/`memory_update`/`link_batch`/`skill`/`schema_migration`/`budget_raise`), requester, task_id, tool, args JSON, risk (`low`/`medium`/`high`), summary, diff_ref, status (`pending`/`approved`/`denied`/`expired`/`auto_approved`), rule_id, decided_via (`ui`/`voice`/`native_dialog`), decided_at, expires_at | The approvals tray. |
| `permission_rules` | id, agent_id (or `*`), tool (glob), decision (`allow`/`ask`/`deny`), scope JSON (paths, domains, max args), applies_when_tainted (bool), expires_at | **Protected.** Changed only from the UI by you, never by an agent. |
| `memories` | id, type (`episodic`/`semantic`/`procedural`), scope (`shared`/`agent:<id>`/`self`), content, data JSON, importance, strength, status (`active`/`proposed`/`superseded`), supersedes_id, source_item_id, source_message_id, source_event_id, valid_from, valid_to, last_used_at | Provenance is mandatory. The Self profile is `scope='self'`. `proposed` = awaiting your approval. Deletion is a hard delete plus vector removal. |
| `skills` | id, name, version, path, description, created_by, status (`proposed`/`approved`/`retired`), eval_score, approved_at | Procedural memory. Files in `skills/`. |
| `conversations` / `messages` | conversations: id, title, agent_id, project_id, channel (`chat`/`voice`/`command_bar`), vault_item_id · messages: id, conversation_id, role, agent_id, content, citations JSON, task_id, modality, tokens | Each conversation is also saved to the vault as Markdown (`conversations/yyyy/mm/…md`). |
| `jobs` | id, kind, item_id, priority_class, priority, status (`queued`/`leased`/`succeeded`/`dead`/`cancelled`), attempts, max_attempts, run_after, lease_owner, lease_expires_at, progress, payload JSON, result JSON, error, idempotency_key (unique while the job is open) | The queue (ADR-0002). A worker claims with `UPDATE … RETURNING`. An expired lease returns the job to `queued`. A failed attempt goes back to `queued` with backoff until `max_attempts`, then `dead`. No `depends_on`: a stage enqueues the next one (ADR-0010). |
| `models` / `model_assignments` | models: id, role, provider (`ollama`/`onnx`/`llamacpp`/`cloud`), name, digest, license, quant, size_bytes, vram_mb, benchmark JSON, installed_at · model_assignments: tier (`local-fast`/`local-large`/`vision`/`embed_text`/`rerank`/`embed_image`/`stt`/`tts`/`ocr`/`cloud`), model_id | The Model Manager. |
| `usage_ledger` | id, ts, task_id, agent_id, provider, model, tokens_in, tokens_out, cost_usd, cache_hit | Feeds the budget meter. Local calls cost $0 but are still counted. |
| `settings` | key, value JSON, protected (bool), updated_at | Budget caps, consent defaults and the kill-switch hotkey are `protected` (UI-only writes). |
| `api_keys` | id, name, scopes, key_hash, created_at, last_used_at, revoked_at | Local API access. |
| `errors` | id, fingerprint, service, kind, message, stack, context JSON, first_seen, last_seen, count, severity, status (`new`/`triaged`/`in_progress`/`fixed`/`ignored`), forge_issue_id | Structured error capture (Forge input). |
| `forge_issues` / `forge_proposals` | issues: id, title, error_ids JSON, severity, frequency, status · proposals: id, kind (`repair`/`dependency`/`model`/`prompt`/`perf`/`feature`), issue_id, title, root_cause, branch, base_commit, head_commit, diff_ref, verification JSON, critic_review, sentinel_review, risk, rollback_plan, touches_protected (bool), status, applied_commit, decided_at | §7. |
| `backups` | id, kind (`scheduled`/`pre_upgrade`/`pre_migration`/`manual`), target, restic_snapshot_id, status, bytes_added, started_at, finished_at, verified_at | Sentinel test-restores update `verified_at`. |
| `watchlists` (Phase 6) / `web_cache` | watchlists: id, kind (`topic`/`page`), query_or_url, schedule, last_checked, last_hash · web_cache: url_hash, url, fetched_at, ttl_s, status, content_path | |
| `schema_migrations` | version, name, checksum, applied_at | Each migration has a tested `down`. |

Deletion is real. `DELETE item` removes the original, all versions, sidecar, thumbnails, chunks/FTS rows, vectors in every LanceDB table, cache entries and trace files that reference it. The trash is a visible 30-day holding area (configurable, can be skipped with "delete permanently"); emptying it runs the same purge. Restic snapshots still hold old data until the next `forget --prune`. The UI says so and offers "purge from backups too".

### 4.2 `events.db`

| Table | Key fields | Notes |
| --- | --- | --- |
| `events` | seq (INTEGER PK), id, ts, type, source (service), actor, subject_type, subject_id, correlation_id, causation_id, payload JSON, schema_version | Only events marked *persisted* in §5.3 are written. High-rate ones (`chat.token`, `job.progress`, `voice.level`) are live-only. Indexes: (ts), (type, ts), (subject_id), (correlation_id). Powers the timeline and time travel. |

### 4.3 `audit.db` (protected, append-only)

| Table | Key fields | Notes |
| --- | --- | --- |
| `audit_log` | seq, ts, actor, action, target_type, target_id, details JSON, outcome, task_id, prev_hash, hash | `hash = sha256(prev_hash ‖ canonical_json(row))`. `BEFORE UPDATE` / `BEFORE DELETE` triggers `RAISE(ABORT)`. Only Core's protected audit writer opens it read-write. Sentinel verifies the chain nightly. **Details store ids and hashes, never vault content or titles**, so deleting an item leaves no copy of it here. The UI resolves ids to titles live and shows "[deleted item]" afterwards. |

Actions logged: `tool.call`, `file.write`, `file.delete`, `net.request`, `approval.decided`, `permission.changed`, `consent.changed`, `killswitch`, `setting.changed`, `forge.*`, `backup.*`, `export`, `purge`, `model.pulled`, `api_key.*`.

### 4.4 LanceDB (`.universe/vectors/`)

| Table (one per kind × model) | Columns |
| --- | --- |
| `text__<model>__<ver>` | chunk_id, item_id, vector, item_type, project_ids, captured_at |
| `image__<model>__<ver>` | item_id, vector, item_type, project_ids, captured_at |
| `memory__<model>__<ver>` | memory_id, vector, scope, type |

A model upgrade builds the new table in the background. Search switches over atomically when it's complete, and the old table is dropped after a grace period. Every vector records its producer by construction (the table name), and `item_stages.model_version` tracks it per item.

### 4.5 Vault on disk (your data, readable without the app)

```
D:\UniverseVault\
├─ notes\2026\10\parcel-4471-seller-call.md          # Markdown + YAML frontmatter (Obsidian-compatible)
├─ ideas\2026\10\pricing-tool-tiers.md
├─ photos\2026\10\IMG_2041.jpg                        # original, byte-for-byte
├─ photos\2026\10\IMG_2041.jpg.universe.json          # sidecar: metadata, caption, tags, links, transcript…
├─ songs\2026\03\ember-night-take3.wav  (+ .universe.json)
├─ documents\…  pdfs\…  audio\…  videos\…  code\…  links\2026\10\<slug>.md
├─ projects\ember-wolf-acquisitions.md               # project page (goals, status) as Markdown
├─ conversations\2026\10\2026-10-12-core-pricing.md
└─ .universe\                                         # app index; dot-folder, ignored by Obsidian
   ├─ universe.db  events.db  audit.db  vectors\
   ├─ versions\<item-id>\<n>.<ext>   thumbs\   cache\   traces\   trash\
```

Note frontmatter:

```yaml
---
id: 0199d6a4-7c1e-7b3a-9f10-2c4e8a1b5d77
type: note
title: Parcel 4471 — seller call
created: 2026-10-12T14:14:00Z
status: active
projects: [ember-wolf-acquisitions]
tags: [seller, parcel-4471]
---
```

Rules:

- The note body and the frontmatter are the source of truth for notes. For other items, the DB is the source of truth and the sidecar is a debounced mirror of it.
- Agents never write your files directly. Agent suggestions (tags, links) stay in the DB until you confirm them, and only then is the frontmatter or sidecar updated, creating a version.
- External edits (e.g. in Obsidian) are detected by the watcher and hash change, and become a new version.
- `Rebuild index from vault` reconstructs the DB from files and sidecars. That's the disaster-recovery path if `.universe\` is lost.

---

## 5. API and event outline

Base URL `http://127.0.0.1:47821/api/v1` (port configurable). JSON everywhere. Cursor pagination (`?cursor=&limit=`). Errors use RFC 9457 problem+json. The OpenAPI schema is generated, and `packages/shared-types` is generated from it.

### 5.1 REST

| Area | Endpoints |
| --- | --- |
| System | `GET /health` (no auth, liveness only) · `GET /system/vitals` · `GET /system/services` · `GET /system/hardware` · `POST /system/offline {enabled}` · `GET /system/safe-mode` |
| Session | `POST /session/ws-ticket` → single-use ticket (30 s) |
| Items | `GET /items` (filters: type, project, tag, status, from/to, q) · `POST /items` (note/idea/link) · `GET /items/{id}` · `PATCH /items/{id}` · `DELETE /items/{id}?permanent=` · `POST /items/{id}/open` · `GET /items/{id}/content` · `GET /items/{id}/thumbnail?size=` · `GET /items/{id}/versions` · `POST /items/{id}/versions/{n}/restore` · `GET /items/{id}/pipeline` · `POST /items/{id}/reprocess` · `POST /items/{id}/reveal` (Explorer) · `POST /items/{id}/open-external` |
| Capture / ingest | `POST /capture` (multipart files or JSON `{text,url,title,project,tags}`; **local API**, API-key scope `capture`) · `POST /ingest/paths {paths[]}` (drag-drop from Electron passes paths, no upload copy) · `GET/POST/PATCH/DELETE /watched-folders` · `POST /importers/{kind}/run` |
| Search & recall | `GET /search?q=&mode=keyword\|hybrid&type=&project=&tag=&agent=&from=&to=&limit=` (**local API**, scope `search`) · `POST /recall {q, context}` → `{intent, action, confidence, results[]}` (fast path) · `GET /commands` · `POST /commands/{name} {args}` |
| Chat | `POST /chat {text, conversation_id?, agent_id?}` (202; replies stream as events; a new UUID names a new conversation) · `GET /conversations` · `GET /conversations/{id}/messages` · `POST /conversations/{id}/cancel` · also over WS (`chat.send`, `chat.cancel`) |
| Projects | `GET/POST/PATCH/DELETE /projects` · `POST /projects/{id}/items` · `DELETE /projects/{id}/items/{item_id}` · `GET /projects/{id}/dashboard` · `GET/POST/PATCH /projects/{id}/tasks` |
| Graph | `GET /links?state=&item=` · `POST /links` · `PATCH /links/{id} {state}` · `POST /links/batch-decision` · `GET /layout/{kind}?model=` (cached positions) |
| Tags, collections | CRUD `/tags`, `/collections`, `POST /items/{id}/tags`, `PATCH /items/{id}/tags/{tag} {state}` |
| Jobs & queue | `GET /jobs?status=&kind=` · `POST /jobs/{id}/retry` · `POST /jobs/{id}/cancel` · `POST /queue/pause` · `POST /queue/resume` |
| Agents & tasks | `GET /agents` · `GET/PUT /agents/{id}` (YAML, validated) · `POST /agents/{id}/clone` · `POST /agents/{id}/enabled {bool}` · `POST /agents/{id}/run {input}` · `GET /tasks?agent=&status=` · `GET /tasks/{id}` (with trace) · `POST /tasks/{id}/cancel` · `GET /skills` · `POST /skills/{id}/decision` |
| Approvals | `GET /approvals?status=pending` · `POST /approvals/{id}/decision {approve, remember_rule?}` (Forge patches are excluded: §7) |
| Memory | `GET /memories?scope=&type=&q=` · `PATCH/DELETE /memories/{id}` · `GET /self-profile` · `POST /memories/{id}/decision` (proposed updates) |
| Models | `GET /models` · `POST /models/pull {provider,name}` (streams progress events) · `DELETE /models/{id}` · `GET/PUT /models/assignments` · `POST /models/{id}/benchmark` · `GET /models/recommendation` |
| Budget | `GET /budget` (month-to-date by agent/model) · `PUT /budget/caps` (protected: UI session only) |
| Settings & permissions | `GET/PATCH /settings` (protected keys rejected unless the UI session confirms) · `GET/PUT /permissions/rules` (UI session only) |
| Consent | `GET /consent` (read-only for Core; the source of truth is Electron main, which pushes state changes to Core) |
| Voice | `WS /ws/voice` (binary PCM 16 kHz frames up; transcripts, states and TTS audio chunks down) · `GET /voices` |
| Vision | `POST /vision/frames` (main posts consented frames) · `POST /vision/ask {frame_ids, q}` · `POST /vision/save {frame_id}` |
| Research (P6) | `POST /research {q, mode: quick\|deep}` · CRUD `/watchlists` |
| Timeline & audit | `GET /events?since_seq=&type=` (replay; `from`/`to`/`subject` filters in Phase 9) · `GET /events?tail=N` (newest N) · `GET /timeline?from=&to=` (aggregated activity) · `GET /audit?actor=&action=&from=&to=&q=` · `GET /audit/verify` |
| Errors | `POST /errors` (renderer/main error capture) · `GET /errors?status=` |
| Forge (P5) | `GET /forge/issues` · `GET /forge/proposals` · `GET /forge/proposals/{id}` (diff, test report, reviews) · `POST /forge/report {text, screenshot_frame_id?}` · `POST /forge/proposals/{id}/reject` · *apply/rollback are supervisor-only* |
| Backups | `GET /backups` · `POST /backups/run` · `POST /backups/{id}/restore {scope}` · `POST /backups/test-restore` |
| Privacy | `GET /privacy/summary` (what's stored, captured and sent where) · `POST /privacy/purge {scope}` · `POST /export {format: vault-zip\|json}` |
| Internal | `POST /internal/events` (workers/voice/models publish; internal token) · `POST /internal/heartbeat` |

**Supervisor control API** (separate loopback port, its own token, held only by Electron main). Phase 1: `GET /status` · `POST /services/{name}/restart` · `POST /services/{name}/kill` (simulates a crash) · `POST /safe-mode/exit` · `POST /shutdown` · `GET /logs/{service}?tail=`. Phase 3: `POST /killswitch {engaged}`. Later: `POST /releases/apply {proposal_id, head_commit, approval_nonce}` · `POST /releases/rollback {to}` (Phase 5).

### 5.2 WebSocket `/ws` (multiplexed)

Client → server: `{op:"subscribe", topics:["item.*","job.*","agent.*","approval.*","chat.<conversation_id>"]}` · `{op:"unsubscribe", …}` · `{op:"chat.send", conversation_id?, agent?, text, context}` · `{op:"chat.cancel", conversation_id}` · `{op:"ping"}`

Server → client: `{kind:"event", event:<envelope>}` · `{kind:"ack", op, ok, error?}` · `{kind:"pong"}`

Event envelope:

```json
{
  "id": "0199d6b2-…", "seq": 18234, "ts": "2026-10-12T14:20:11.204Z",
  "type": "item.processed", "source": "worker-1", "actor": "system",
  "subject": {"type": "item", "id": "0199d6a4-…"},
  "correlation_id": "task-or-trace-id", "causation_id": "event-id",
  "payload": {}, "v": 1
}
```

Delivery: in-process asyncio pub/sub in Core, fanned out to WS subscribers, agent triggers, the audit writer and Forge. Workers and other services publish via `POST /internal/events`. Persisted events are written to `events.db` *before* fan-out, so the timeline never misses one the UI saw. On reconnect, the UI resumes with `?since_seq=`.

### 5.3 Event catalog (P = persisted)

| Domain | Events |
| --- | --- |
| Items | `item.created` P · `item.updated` P · `item.deleted` P · `item.opened` P · `item.processed` P · `item.trashed` P · `item.restored` P |
| Pipeline / jobs | `pipeline.stage.started` · `pipeline.stage.completed` P · `pipeline.stage.failed` P · `job.queued` · `job.progress` · `job.completed` · `job.failed` P · `job.dead` P |
| Graph | `link.suggested` P · `link.confirmed` P · `link.rejected` P · `tag.suggested` · `tag.confirmed` P · `project.created` P · `project.updated` P · `idea.stage_changed` P · `idea.promoted` P |
| Search / navigation | `recall.performed` P (query, top result ids; powers "what did I look at") · `view.changed` (layout/zoom) · `navigator.action` |
| Chat | `chat.message` P · `chat.started` (model chosen) · `chat.token` · `chat.completed` · `chat.cancelled` · `chat.failed` P (with `code`, `error`, `hint`) |
| Agents | `agent.started` P · `agent.step` · `agent.tool_call` P · `agent.message` (agent→agent) P · `agent.completed` P · `agent.failed` P · `agent.reloaded` P |
| Approvals | `approval.requested` P · `approval.decided` P · `approval.expired` P |
| Memory | `memory.created` P · `memory.proposed` P · `memory.updated` P · `memory.deleted` P · `consolidation.completed` P · `contradiction.detected` P |
| Consent & safety | `consent.changed` P (mic/screen/camera on/off, scope) · `killswitch.engaged` P · `killswitch.released` P · `offline.changed` P · `capture.started` P · `capture.stopped` P · `capture.saved` P |
| Budget | `budget.usage` · `budget.warning` P (50/80 %) · `budget.cap_reached` P |
| Voice | `voice.state` (idle/listening/thinking/speaking) · `voice.level` · `voice.transcript.partial` · `voice.transcript.final` P · `voice.tts.started` · `voice.tts.stopped` · `voice.barge_in` |
| Errors & health | `error.raised` P · `service.started` P · `service.crashed` P · `service.restarted` P · `safe_mode.entered` P · `governor.paused` P · `governor.resumed` P |
| Forge / Sentinel | `forge.issue.triaged` P · `forge.proposal.created` P · `forge.proposal.verified` P · `forge.applied` P · `forge.rolled_back` P · `sentinel.alert` P · `backup.completed` P · `backup.restore_tested` P |
| Models | `model.pull.progress` · `model.loaded` · `model.unloaded` · `model.assignment_changed` P |

### 5.4 Tool interface (agents)

```python
class Tool(Protocol):
    name: str                      # "vault.search"
    description: str
    input_model: type[BaseModel]   # Pydantic → JSON Schema for the LLM
    tier: Literal["read", "write", "system"]
    side_effects: bool             # false = safe to call from tainted context
    network: bool                  # routes through the egress gate
    timeout_s: float
    async def run(self, args: BaseModel, ctx: ToolContext) -> ToolResult: ...
```

MCP servers are wrapped as `Tool`s (tier defaults to `write`, `side_effects=True`, so they ask first until you set a rule). Plugins implement typed provider interfaces (`LLMProvider`, `Embedder`, `Reranker`, `STT`, `TTS`, `WakeWord`, `VLM`, `OCR`, `SearchProvider`, `Importer`), registered via `plugins/<kind>/<name>/manifest.yaml`.

---

## 6. Universe UI concept

### 6.1 Principles

1. **The beauty is the navigation.** Every visible object is a real item, project or agent. No decorative clutter beyond the starfield and nebula backdrop.
2. **Calm by default.** Labels appear on approach. The HUD sits at the edges, the centre belongs to the universe, and motion only happens when something changed.
3. **Keyboard first, voice equal, mouse optional.** Every action is a command (cmdk). Every panel is reachable with the keyboard and labelled for screen readers.
4. **2D is never a downgrade.** Grid, List, Table, Timeline, Kanban and Map views of the same query are always one keystroke away.

### 6.2 Design tokens (`packages/design-tokens/tokens.json`, the single source)

| Token group | Values (initial) |
| --- | --- |
| Base | `space.0 #05070D` (background) · `space.1 #0A0F1C` · `space.2 #111829` · nebula gradient stops `#1B1240`, `#0B2A3A` at 6–10 % opacity |
| Glass | fill `rgba(16,24,42,0.55)` · blur 20 px · hairline `1px rgba(160,190,255,0.12)` · radius 12 / 16 / 24 · focus glow `0 0 0 1px accent, 0 0 24px accent/25%` |
| Accent | primary **cyan `#3EE0FF`** · secondary **violet `#9B7BFF`** |
| Semantic (≤ 8 hues, always paired with a glyph/shape) | cyan: notes · violet: ideas · amber `#FFB547`: photos/video · rose `#FF5FA2`: songs/audio · green `#5BE49B`: code · blue `#5B8CFF`: docs/files · slate `#8A97B5`: links/neutral · red `#FF5C5C`: danger/live-capture indicators only |
| Text | `#E8EEFF` primary · `#A9B4D0` secondary · `#808CAC` tertiary. Contrast ≥ 4.5:1 on glass (high-contrast theme raises it to 7:1) |
| Type | Space Grotesk 500/600 (headings, HUD labels) · Inter 400/500 (body) · JetBrains Mono 400 (data, code, metrics). Scale 12/14/16/20/24/32 |
| Spacing | 8 px grid: 4 · 8 · 16 · 24 · 32 · 48 · 64 |
| Motion | `fast 150ms` · `base 200ms` · `slow 250ms` (UI) · `flight 600–1200ms` (distance-scaled, ease-in-out-cubic) · springs: stiffness 260, damping 28 · `prefers-reduced-motion` → fades only, instant camera jumps |
| Z-layers | universe 0 · HUD 10 · panels 20 · command bar 30 · approvals/dialogs 40 · consent indicators 50 (always on top) |

Agents get one of the 8 hues plus a unique *probe shape* (so two agents sharing cyan stay distinguishable without relying on colour).

*Phase 4 as built:* quality presets Ultra / High / Balanced / Lite (Auto picks from the GPU and steps down when frames drop; software rendering → Lite). Lite is a sigma 2D graph of the same data, sharing selection, search and viewers. Viewers (`hud/viewers/`) open over the dimmed universe; the navigator card (minimap, breadcrumb, zoom level, layouts, time slider) sits bottom left. Measured numbers are in [PHASE-4.md](PHASE-4.md).

### 6.3 Main screen wireframe (Universe view, HUD visible)

```
+--------------------------------------------------------------------------------------------------------+
| (*) UNIVERSE   +---------------------------------------------------+  [MIC*] [SCR ] [CAM ]   ONLINE    |
|                | /  Search or command...                Ctrl+Space |  $0.00 / $10   GPU 41%   [ KILL ] |
|                | [type v] [project v] [date v] [tag v]             |                                   |
|                +---------------------------------------------------+                                   |
+--------+-------------------------------------------------------------------------------+---------------+
| AGENTS |                  .           *  DevMind                .                      | CONTEXT       |
|        |       .                   ( galaxy - 312 )                     .              | +-----------+ |
| o Core |                                                                               | |  preview  | |
| > Libr |     @ Ember Wolf Acq.            .        ~~> comet x3                        | +-----------+ |
|   tag  |    ( galaxy - 1,204 )                          (inbox)                        | Parcel 4471   |
| - Scri |       \                                                                       | seller call   |
| - Rese |        `--- filament ---.          (O) CORE              # Algo bot           | Note - Ember  |
| ! Forg |                          \                               ( galaxy - 88 )      | Wolf - 2d ago |
|   (2)  |    [=] UNIVERSE src       `-- > Librarian probe                               | -----------   |
| - Sent |    station - tests ok                                                         | AI summary    |
|        |                                                                               | Owner wants   |
| [+]    |                  .                .                      .                    | out by Nov... |
|        |                                                                               | Links (4)     |
|        |                                                                               | Versions (3)  |
|        |                                                                               | [Open] [Pin]  |
|        |                                                                               | [Link] [...]  |
+--------+-----------------------+------------------------------+------------------------+---------------+
| [minimap .  @  .  #]           |          .-----------.       | APPROVALS (2)  >                       |
| Universe > Ember Wolf > Note   |         (  ( o )  ) orb      | ACTIVITY  Librarian tagged 12 items    |
| Layout: Project  [1][2][3][4]  |          '-----------'       |           Scribe drafted meeting...    |
|                                | idle - "Hey Universe" - hold |                                        |
|                                |   Ctrl+Alt+Space to talk     |                                        |
+--------------------------------+------------------------------+----------------------------------------+
```

Legend: `(O)` Core (home star) · `@ * #` galaxies (projects) · `[=]` space station (code repo, status light) · `~~>` comet (inbox capture) · `>` agent probe · `--- filament ---` link (dashed = suggested) · `o` agent idle, `>` working, `!` waiting for approval, `-` disabled/off · `[MIC*]` = live (red pill, pulsing, always on top).

Zoom levels: **Universe** (galaxies as sprites, galaxy labels only) → **Galaxy** (stars/planets/pulsars as instanced meshes, item labels within ~N px) → **System** (one item and its linked neighbours, orbits visible) → **Item** (a glass viewer unfolds from the object and the universe dims behind it).

### 6.4 Command bar (global hotkey, over any app)

```
+------------------------------------------------------------------+
| /  photos from the lake last summer                        [esc] |
|    type:photo   date: 2026-06-21 .. 2026-09-22   "lake"          |
+------------------------------------------------------------------+
|  1  [planet] Lake sunset, dock          Jul 14 - Photos          |
|  2  [planet] Lake Travis - kayak        Aug 02 - Photos          |
|  3  [star]   Lake trip packing list     Jun 30 - Note            |
+------------------------------------------------------------------+
|  Enter open - Ctrl+Enter fly to - Tab actions (pin, link, move)  |
|  > Ask Core: "photos from the lake last summer"                  |
+------------------------------------------------------------------+
```

The command bar is a separate always-on-top frameless window that is pre-created and kept hidden, so showing it is a `show()`, not a launch (< 150 ms budget). Parsed filters appear as chips you can delete. The last line hands off to the smart path. With a high-confidence single result, `Enter` flies there and opens it. Several results form the 3D constellation in front of the camera, with matching numbers for "the second one".

### 6.5 Key interactions

| Input | Action |
| --- | --- |
| `Ctrl+Space` (global, configurable; conflict detected if an IME owns it) | Command bar |
| `Ctrl+Alt+Space` hold (global) | Push-to-talk (key-up detection needs `uiohook-napi`, MIT) |
| `Ctrl+Alt+K` (global) + tray + HUD button | **Kill switch** |
| `/` · `Esc` · `H` | Focus search · back / zoom out · fly home to Core |
| `1`–`4` · `G` / `L` / `T` / `K` / `M` | Layouts (Project, Semantic, Time, Graph) · 2D Grid / List / Timeline / Kanban / Map |
| `Z` · `Ctrl+.` | Zen mode · approvals tray |
| Voice | Everything Navigator can do: "take me to Ember Wolf", "the second one", "play it", "zen mode" |

### 6.6 States worth designing explicitly

Cold start (shell in < 3 s, models warming: the Core star pulses slowly and the search bar works keyword-only until embeddings are ready) · empty universe (four seed galaxies plus an "add your first files" comet) · offline (status pill plus Researcher greyed out) · safe mode (static page from Electron main: what failed, last-known-good version, buttons to retry / roll back / open logs) · kill switch engaged (red banner, all probes parked at Core, every capture indicator off) · Lite mode (sigma 2D graph with the same HUD).

---

## 7. Forge safety design

Goal: Forge can fix and upgrade almost anything, yet **cannot** lock you out, delete or rewrite your data, weaken a safety rule or a test, approve its own work, or apply anything without you. Each guarantee is enforced by **deterministic code outside Forge's reach**, not by prompts.

### 7.1 Pipeline

```
 detect ─► triage ─► reproduce ─► diagnose ─► patch ─────► verify ─────────► review ──────► propose
 errors    dedupe    failing     root cause   worktree     full suite in     Critic (code)   card in
 crashes   group     test first  in plain     forge/<id>   sandbox: tests,   Sentinel        approvals
 tests     rank      (must fail  English      minimal      lint, types,      (deterministic  tray
 reports             on base)                 diff         evals, perf vs    checks + LLM
                                                           baseline          review)
                                                                                   │
   ┌───────────────────────────────────────────────────────────────────────────────┘
   ▼
 approve (native dialog in Electron main) ─► supervisor: re-check ─► restic snapshot ─► fast-forward merge
   ─► rebuild (if UI) ─► restart affected services ─► health check ─► watch window ─► promote to LKG
                                                         │ regression at any point
                                                         └─► automatic rollback to LKG + report
```

### 7.2 Hard guarantees and where they're enforced

| Guarantee | Enforcement (outside Forge) |
| --- | --- |
| **Protected core is untouchable** (permissions, consent, kill switch, audit, budget caps, Sentinel, supervisor, update/rollback, Forge's own YAML/limits, `protected-core.txt`, `tests/protected/`, CI and pre-commit config) | `protected-core.txt` globs. Three independent checks: (1) the Sentinel diff check marks `touches_protected`, (2) the **supervisor** re-checks the diff's paths against its *own copy* of the manifest hash before applying and refuses, (3) Forge's worktree tool refuses writes to protected paths. For protected changes Forge can only produce a **manual patch file + explanation** that you apply yourself. |
| **Forge can't apply or approve** | Forge's tools: read the repo, create a worktree, write inside the worktree, run verification in the sandbox, open a proposal. **No merge, apply or approve tool exists.** Apply happens only in the supervisor, triggered by Electron main after a **native OS dialog** (summary + diff hash). Renderer code can't click it, and neither Core nor the renderer holds the supervisor token. |
| **Tests are never weakened** | The Sentinel test-integrity check (AST/diff based) rejects any proposal that deletes or renames tests, adds `skip`/`xfail`/`.only`/`.skip`, loosens assertions, lowers coverage or perf thresholds, or edits eval expectations. The repro test must **fail on base and pass on head**, verified by running both. |
| **Vault data is never deleted or rewritten** | Forge has no vault tools at all. Verification runs against a disposable copy of the seed dataset. Schema migrations need an up+down pair tested on a snapshot copy, a verified restic backup and your approval. Migrations are classed `high` risk automatically. |
| **Nothing breaks permanently** | Pre-apply restic snapshot plus a git tag for each release. The supervisor watches for a window (default 30 min or 200 requests): crash loops, error-rate jump > 2×, health-check failure or perf regression > 20 % trigger an **automatic rollback** to LKG. One-click rollback to any prior release lives in the UI (it goes through the supervisor). |
| **You can never be locked out** | Safe mode (two failed boots → LKG, agents disabled) is served by protected Electron-main code and needs nothing from Core. App lock, consent and the kill switch are protected. `scripts/restore-lkg.ps1` works with the app closed. |
| **Independent review** | Critic (code quality) and Sentinel (safety/privacy/permission impact) are separate agents with separate prompts, and Sentinel's verdict is mostly deterministic: new dependencies (license allowlist + advisories), new network calls or egress rules, permission-tier changes, new file-system paths, new capture or consent code paths. Sentinel's YAML and code are protected. |
| **No spam** | ≤ 5 proposals/day (protected setting), batched into a daily digest, duplicates suppressed by error fingerprint. |
| **Everything is on the record** | Every Forge step is written to the audit log by Core's protected audit writer (Forge can't write to `audit.db`). Proposals keep the diff, test report, reviews and decision forever. |
| **Prompt injection can't steer it** | Logs, error messages, screenshots and web pages are untrusted data. They're quoted in Forge's context with provenance markers, and since Forge's only side effects are inside a sandboxed worktree, an injected instruction can at worst produce a bad proposal, which then still faces verification, review and you. |
| **Auto-apply is narrow and off** | Off by default (protected). When you enable it, it only covers categories you choose (e.g. patch-level dependency bumps that pass everything), still snapshots, still watches, and still auto-rolls back. |

### 7.3 The same policy engine guards every agent

Every tool call passes `policy.check(agent, tool, args, task)`:

1. **Tier gate:** the tool's tier must be ≤ the agent's `permission_tier`. Agents can't raise their own tier (the YAML tier field is validated on reload; tier increases need your confirmation in the UI).
2. **Rules:** a matching `permission_rules` entry decides allow / ask / deny. Default: `read` → allow, `write` → per-agent `requires_approval` list, `system` → always ask.
3. **Taint:** once untrusted content (web, file text, OCR, email, MCP output) has entered a task's context, `tainted = true`. From then on every tool with `side_effects` or `network` asks you, unless a rule explicitly says `applies_when_tainted`.
4. **Budget and limits:** steps, tokens, wall time and money are checked *before* each LLM call. Loop detection fires on the same tool + args hash 3× in a row.
5. **Kill switch / offline:** checked on every call. When engaged, everything is denied immediately.

*Phase 3 as built (ADR-0011):* the engine lives in `protected/policy.py` (with `permissions.py`, `budget.py`, `killswitch.py`) and runs the checks in this order: kill switch → tier gate → rules (most specific first, the strictest wins ties) → taint → defaults. MCP tools default to *ask*. The loop itself is unprotected (`services/agents/runtime.py`) and asks the policy through a `Policy` protocol, so a missing policy module means no tools at all, never unchecked tools.

### 7.4 Releases, last-known-good and safe mode

- Dev checkout: releases are git tags `release/<n>`. The LKG is a pristine worktree at `.universe-runtime/lkg/`.
- Installed build: the signed installer provides Electron + supervisor + an initial app checkout under `%LOCALAPPDATA%\Universe\runtime\`. That checkout is what Forge patches. Rebuilds of the renderer happen as part of apply.
- The supervisor records `boot_failures`. Two in a row → boot the LKG with agents disabled, show the safe-mode page with the failing service's last log lines, and let you (and a read-only Forge) diagnose from there. Supervisor state is a JSON file written atomically, so it doesn't depend on SQLite being healthy.

Phase gating: Phase 1 ships the supervisor, LKG, safe mode, structured error capture, the test harness and `protected-core.txt`. Phase 5 ships Forge on top of them.
