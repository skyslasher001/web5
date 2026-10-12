# Phase 0 — Blueprint delivery

Status: **approved 2026-10-12 with the default answers** ("approved use defaults initiate phase 1"). Phase 1 is delivered: see [PHASE-1.md](PHASE-1.md).

Answers recorded:

1. **This repo:** replaced in place by the monorepo. The old landing page is preserved in history (tag `pre-universe`; the tag could not be pushed from the build environment, see PHASE-1.md).
2. **DevMind:** built fresh. DevMind pieces get ported once its repo is available to read.
3. **Container runtime:** Podman + WSL2 (needed from Phase 5/6 for the sandbox and SearXNG).
4. **Voice languages:** English only.
5. **Cloud LLM:** none; the provider slot and caps exist with cloud switched off.

## Where each deliverable is

| SPEC §27 item | Location |
| --- | --- |
| 1. Architecture diagram in text | [ARCHITECTURE.md §1](ARCHITECTURE.md#1-architecture): diagram, processes, trust boundaries, key flows with latency budgets, performance governor |
| 2. Final tech decisions (justification + license) | [ARCHITECTURE.md §2](ARCHITECTURE.md#2-final-tech-decisions): stack table, license flags with alternatives, model shortlist per hardware tier · ADRs in [`adr/`](adr/) |
| 3. Repo folder tree | [ARCHITECTURE.md §3](ARCHITECTURE.md#3-repo-folder-tree) |
| 4. Data model | [ARCHITECTURE.md §4](ARCHITECTURE.md#4-data-model): `universe.db`, `events.db`, `audit.db`, LanceDB tables, vault-on-disk layout |
| 5. API and event outline | [ARCHITECTURE.md §5](ARCHITECTURE.md#5-api-and-event-outline): REST, supervisor control API, WebSocket protocol, event envelope + catalog, tool interface |
| 6. UI concept + text wireframe | [ARCHITECTURE.md §6](ARCHITECTURE.md#6-universe-ui-concept): principles, design tokens, main-screen wireframe, command bar, key bindings, designed states |
| 7. Forge safety design | [ARCHITECTURE.md §7](ARCHITECTURE.md#7-forge-safety-design): pipeline, hard guarantees and where each is enforced, policy engine, LKG and safe mode |
| 8. Hardware info I need | [below](#8-hardware-info-i-need-from-you) + [`scripts/hardware-report.ps1`](../scripts/hardware-report.ps1) |
| 9. Questions (5 max) | [below](#9-questions) |

`SPEC.md` was exported from your Google Doc "UNIVERSE — Master Build Prompt v2" (Oct 12, 2026), since it wasn't in the repo yet. The only change was in §25: the phases are numbered 0–12 again (the Docs export had flattened every phase to "1."). Phase 0 = Blueprint and Phase 2 = Vault + Recall, which matches §27 and §28.

## Decisions that differ from the SPEC defaults (flagged per §26.5)

1. **Custom SQLite job queue instead of huey.** The per-item stage DAG, governor-controlled priority classes, leases and progress events all need to share one table with item state. ([ADR-0002](adr/0002-sqlite-job-queue.md))
2. **Custom agent loop** (picked from the two SPEC options), so permissions, approvals, taint, budget, kill switch and audit are our code. ([ADR-0004](adr/0004-custom-agent-loop.md))
3. **No ORM.** Stdlib `sqlite3` and SQL migrations with tested `down` steps. ([ADR-0003](adr/0003-storage-layout.md))
4. **RapidOCR instead of PaddleOCR:** the same PP-OCRv5 models on ONNX Runtime, without the PaddlePaddle framework. **tinytag instead of mutagen** (mutagen is GPL).
5. **Vision runs inside Core**, and there's a new **models service** (ONNX Runtime) for rerankers, SigLIP and OCR. Mic capture and TTS playback live in the renderer, which gives WebRTC echo cancellation for barge-in without a headset. ([ADR-0001](adr/0001-process-model-and-supervisor.md), [ADR-0005](adr/0005-model-runtimes.md))
6. **Security:** Forge code changes are applied only by the supervisor, after a native OS dialog in Electron main, so neither Core nor the renderer (both patchable by Forge) can apply anything. ([ADR-0006](adr/0006-local-security-model.md))
7. **Pins:** Python 3.12 (Kokoro requires < 3.13) and TypeScript 6.0 (typescript-eslint supports < 6.1). ([ADR-0007](adr/0007-runtime-pins.md))
8. **License policy:** treat the app as distributable from day one. Copyleft only as an unmodified separate process. No non-commercial weights. ([ADR-0008](adr/0008-license-policy.md))

## 8. Hardware info I need from you

The quickest way: on the Windows PC, from the repo root, run

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\hardware-report.ps1
```

and paste `universe-hardware-report.txt` into the chat. The script is read-only, installs nothing, and doesn't collect serial numbers, user names or the computer name. It covers items 1–6 and 10 below. Items 7–9 and 11–13 only you can answer.

| # | What | Why it changes the build |
| --- | --- | --- |
| 1 | Windows edition and build (Home / Pro, 23H2 / 24H2 / 25H2…) | WSL2 and container options; Windows Hello APIs |
| 2 | CPU model, cores/threads, virtualization enabled in firmware | CPU-tier fallbacks; WSL2/containers need virtualization |
| 3 | Total RAM (and speed) | Model offload headroom (MoE expert offload needs ≥ 32 GB); worker count |
| 4 | Every GPU: model, **VRAM**, driver version (NVIDIA: CUDA driver version) | Picks the hardware tier and model loadout (ARCHITECTURE.md §2.3), plus the ONNX execution provider (CUDA vs DirectML) |
| 5 | Drives: SSD/NVMe/HDD, size, free space | Vault, model store (20–60 GB) and index placement |
| 6 | Displays: count, resolution, refresh rate | FPS target (60 vs 120/144 Hz) and quality-preset defaults |
| 7 | **Vault path** (e.g. `D:\UniverseVault\`) and a rough size of what you'll import first (GB; approximate counts of photos / songs / videos / docs) | Disk planning, first-ingest time estimate, seed-data scale for perf tests |
| 8 | **Backup target:** external drive letter, NAS share path, or "none yet"; any cloud bucket you'd want later | Restic repository setup in Phase 2 |
| 9 | **Audio setup:** mic type (headset / USB desk mic / laptop array) and speakers vs headphones | Echo-cancellation mode vs headset mode for barge-in |
| 10 | Webcam present? | Camera toggle scope (Phase 8) |
| 11 | Laptop or desktop; do you game or run other fullscreen GPU-heavy apps while UNIVERSE runs? | Governor thresholds and yield rules |
| 12 | Already installed: Ollama, WSL2, Docker/Podman, Git, Python, Node | Phase 1 setup steps (the script lists these) |
| 13 | Internet: unmetered? Rough download speed? | First model pull is ~5–40 GB depending on tier |

## 9. Questions

Each has a default, so Phase 1 can start even if you only answer some.

1. **This repo.** `skyslasher001/web5` currently holds an unrelated Bolt landing page ("OmniWeb Agency", with an unused Supabase dependency). OK to replace it with the UNIVERSE monorepo at the repo root, after tagging the current state `pre-universe` so nothing is lost? Or do you want UNIVERSE in a new repo named `universe`?
   *Default: replace in place, tag first.*
2. **DevMind reuse.** Which repo is DevMind, and which parts should I reuse (Electron shell/preload, the Python sidecar launcher, chat UI, code editor, model management)? I'll need it added to the session to read it.
   *Default: build fresh in Phase 1, and port DevMind pieces once I can read it.*
3. **Container runtime** for the Builder/Forge sandbox and SearXNG: **Podman + WSL2** (Apache-2.0), **Docker Desktop** (free for personal use and small businesses under 250 employees and $10M revenue), or **none** (then SearXNG is skipped in favour of free search APIs, and the code sandbox falls back to a restricted Windows process with no network; that's much weaker isolation, and I'd flag it in the UI).
   *Default: Podman + WSL2.*
4. **Voice languages.** English only, or others too? English-only allows faster English-specific STT models and Kokoro's strongest voices. Multilingual changes the STT, TTS and wake-word choices.
   *Default: English only.*
5. **Cloud LLM.** Stay 100% local until later, or wire one opt-in provider in Phase 3? If so, which provider (any OpenAI-compatible endpoint) and what hard monthly cap?
   *Default: none; the provider slot and caps exist with cloud switched off.*

## What approving means, and what Phase 1 delivers

Approve (or amend) the blueprint, answer what you can above, and send the hardware report. Phase 1 (Foundation) then delivers, per SPEC §25:

- the monorepo skeleton from ARCHITECTURE.md §3, with `pnpm dev` as the one-command start
- an Electron shell on the design tokens with the base HUD frame
- FastAPI with WebSocket streaming chat to a local Ollama model (Core agent, no tools yet)
- SQLite schema v1 across the three DB files, with the four seed galaxies from SPEC §28
- the event bus, structured logging and error capture
- the stdlib supervisor with restart, last-known-good and safe mode, plus `protected-core.txt`
- hardware detection with a model recommendation
- pytest, Vitest and a Playwright Electron smoke test, pre-commit, and CI on `windows-latest` + `ubuntu-latest`

Phase 1 is done when you launch the app, chat with streaming replies, kill the backend and watch it auto-restart, and all tests pass.

## Known limitations of this phase

- **Model shortlist wasn't checked against model cards.** Hugging Face and ollama.com were blocked by the network policy of the environment this blueprint was written in. The shortlist in ARCHITECTURE.md §2.3 comes from web search on 2026-10-12, and several sources disagree on details. Phase 1 verifies every card (license, size, availability) and benchmarks locally before anything becomes a default.
- **Package versions and licenses were checked live** against npm and PyPI, including Windows wheel availability for the Python ML stack.
- **There's no Windows machine in my build environment.** `scripts/hardware-report.ps1` parses cleanly under PowerShell 7.6 and its error handling was smoke-tested on Linux, but the Windows cmdlets themselves (CIM, Storage, PnP) have only run on your PC once you run it. Phase 1 adds CI on `windows-latest` so Windows-specific code is tested on Windows from then on.
- **Ctrl+Space** (the SPEC's default hotkey) toggles the IME for CJK input methods. The app detects a failed registration and asks for another binding.
- **Ingestion latency budgets and FPS at 50k items** are design targets here. They're measured in Phases 2 and 4 with the seed generator.

## What's next

Phase 1 (Foundation), after your go-ahead.
