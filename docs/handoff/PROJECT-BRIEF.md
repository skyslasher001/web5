# UNIVERSE: the complete project brief

Everything about the project so far, in one document, for any AI (or person) taking over. It's written to
work on its own: an assistant that only gets this file can understand the project, its state and its rules.
The details live in the files it links to. Written 2026-10-14; updated 2026-10-19 after Phase 6 was delivered.

> **If you read nothing else**
> - **What:** UNIVERSE, a local-first Windows desktop "digital brain". Everything the owner has (projects,
>   notes, files, photos, songs, links, conversations) lives in one navigable 3D universe, run by a team of
>   local AI agents. Electron + React UI, Python/FastAPI services, SQLite + LanceDB, local models via Ollama.
> - **State:**
>   - Phases 0–4 are built and approved.
>   - Phases 5 (Forge + Sentinel: self-repair), 6 (Research: live web, cited, injection-defended) and 7 (Voice)
>     are built, delivered and reviewed (2026-10-21), and wait for the owner's approval. The Phase 5 and Phase 7
>     protected-core patches are applied, and so are the review's protected-core fixes (2026-10-22,
>     [review-fixes-protected](../proposals/review-fixes-protected.md)). Forge changes can now be approved.
>   - A full sweep of every file (2026-10-22/23) fixed 50 bugs on the branch, each with a regression test. Ten
>     protected-core fixes wait for the owner as [sweep-fixes-protected](../proposals/sweep-fixes-protected.md).
>   - The SearXNG sidecar is an opt-in proposal gated on a container runtime.
>   - Next is Phase 8 (vision).
> - **Where the code is:** the private GitHub repo `skyslasher001/web5`, branch
>   **`claude/phase-0-delivery-zuqlfx`**. Not `main`: that still holds an old unrelated landing page.
> - **Rules that are never broken** (full list in `AGENTS.md`):
>   - Never edit the protected core (propose a patch instead).
>   - Never weaken a test.
>   - Never delete or rewrite vault data.
>   - No secrets in the repo.
>   - Network only through the egress gate.
>   - Permissive licenses only.
>   - Mic, screen and camera stay off by default.
> - **How to continue:** read [`AGENTS.md`](../../AGENTS.md), then [`docs/HANDOFF.md`](../HANDOFF.md). "Deliver
>   Phase N" means build exactly SPEC §25's scope for that phase, with tests, docs and a demo, then stop for
>   review.

## Contents

1. [The vision](#1-the-vision)
2. [The owner and how to work with them](#2-the-owner-and-how-to-work-with-them)
3. [Where things stand](#3-where-things-stand)
4. [What exists today](#4-what-exists-today)
5. [Architecture in one page](#5-architecture-in-one-page)
6. [The agents](#6-the-agents)
7. [Decisions](#7-decisions)
8. [Rules for whoever works on this](#8-rules-for-whoever-works-on-this)
9. [Open items](#9-open-items)
10. [Roadmap](#10-roadmap)
11. [The repository](#11-the-repository)
12. [Running and testing](#12-running-and-testing)
13. [Measured numbers](#13-measured-numbers)
14. [Glossary](#14-glossary)
15. [Every document](#15-every-document)

## 1. The vision

From the owner's spec (SPEC §1): *"a local-first Windows desktop app that works as my digital brain. Every
project, note, idea, song, file, photo, link, and conversation lives in one navigable, interactive universe.
A team of AI agents runs it. They organize, research, create, see my screen when I allow it, talk with me by
voice, fix their own bugs, and upgrade the system over time. Anything I have ever put in must be pullable on a
whim, by voice or by typing, in under a second."* The design target is *"a premium sci-fi command center that
stays neat, fast, and calm."*

**The neural universe.** On 2026-10-14 the owner sharpened the idea:

> *"it will be similar to a brain, we are creating a neural network essentially, in the shape of a universe
> much like life itself … the agents will act as neurons while the subjects (the galaxies) will be like
> synapses … a smooth nice scalable zoom in and zoom out … all of the vocal systems needed … to receive
> transmission."*

How that maps onto the build ([`docs/VISION-neural-universe.md`](../VISION-neural-universe.md)):
- **Agents are neurons.** They fire, visibly: probes fly along the link paths between items.
- **Galaxies are synaptic hubs, and links are synapses.** Links strengthen with use. That's a SPEC requirement
  for Phase 9, and firings have been recorded since Phase 4.
- **Signal pulses** travel along links whenever you or an agent move from one item to another. Built.
- **Smooth zoom** goes from the whole universe down to a single star. Built.
- **The voice receive chain** ("transmissions") is fully specified for Phase 7.

**Non-negotiables** (SPEC §3):
- local-first, offline except web research and optional cloud models;
- permissive open source only;
- $0 per query by default, with paid APIs behind hard caps;
- consent for mic, screen and camera, off by default;
- the vault stays plain readable files with real deletion;
- every capability is a swappable plugin;
- self-healing, never self-destroying;
- the performance budgets (SPEC §24) are requirements;
- every phase ends with real, runnable output.

**Seed galaxies** (SPEC §28), created at first run:
- **Ember Wolf Acquisitions:** the owner's vacant-land wholesaling business.
- **DevMind:** the owner's offline AI developer IDE, on the same stack.
- **Algo trading bot:** Python, perpetual futures.
- **UNIVERSE itself:** its own source, so Forge can repair it.

## 2. The owner and how to work with them

- **Who:** *"a technically hands-on solo builder"* (SPEC §2). They want a senior principal engineer, product
  architect and UI/UX designer.
- **Tone:** be direct, no fluff, ship working code, push back with reasons and a better option, and hold a
  premium design bar.
- **Messages are short.** "approved." accepts a phase and starts the next. Offered options, they have always
  picked the recommended one. Their every message and answer so far, verbatim: [`DECISIONS.md`](DECISIONS.md).
- **What they care about:**
  - one phase at a time, with a stop for review;
  - real, tested output;
  - an interface that feels smooth and alive;
  - being able to hand the project to any AI.
- **Platform:** Windows 10/11 PC. Their hardware details were asked for in Phase 0 and haven't arrived yet.
- **Phase 0 defaults they accepted:**
  - replace the old site in this repo;
  - build fresh, not reusing DevMind until it's shared;
  - Podman + WSL2 for containers;
  - English-only voice;
  - no cloud LLM for now.

## 3. Where things stand

| Phase (SPEC §25) | Status | "Done when" and result | Record |
| --- | --- | --- | --- |
| 0 Blueprint | Approved 2026-10-12 (all defaults) | Architecture, decisions, data model, API, UI concept, Forge safety design | [PHASE-0](../PHASE-0.md) |
| 1 Foundation | Delivered 2026-10-12 | Launch, streaming chat, kill the backend and it restarts, tests pass: **passed** | [PHASE-1](../PHASE-1.md) |
| 1.5 Fixes | Approved 2026-10-13, protected patch applied | Every known issue fixed, verified against a real Ollama | [PHASE-1.5](../PHASE-1.5.md) |
| 2 Vault + Recall | Approved 2026-10-13 | 500 mixed files, each found by keyword or meaning in under a second: **passed** (slowest 309 ms) | [PHASE-2](../PHASE-2.md) |
| 3 Agent engine | Approved 2026-10-13, protected patch applied | "Find my notes about X, summarize them, link them to project Y" with a full audit trail: **passed** | [PHASE-3](../PHASE-3.md) |
| 4 Universe interface | Approved 2026-10-14 | 50k items, FPS budget, search flies the camera to results. **Search passed. FPS not yet proven:** there's no GPU here, so the owner must run `pnpm bench:universe` | [PHASE-4](../PHASE-4.md) |
| 5 Forge + Sentinel v1 | **Delivered 2026-10-14, reviewed 2026-10-21, protected patch and review fixes applied**; waiting for approval | Inject a bug, Forge finds it and proposes a tested fix, approve, it applies, one-click rollback: **passes** | [PHASE-5](../PHASE-5.md), [proposal](../proposals/phase-5-protected-core.md) |
| 6 Research | **Delivered 2026-10-19** | A deep-research report with cited sources lands in the vault, offline/kill block it, an injection corpus can't make it act: **passed** (`tests/integration/test_research.py`). Default search is a gated httpx request; the SearXNG sidecar is an opt-in proposal | [PHASE-6](../PHASE-6.md), [ADR-0015](../adr/0015-phase-6-research.md) |
| 7 Voice | **Delivered 2026-10-19, reviewed 2026-10-21, consent patch applied**; waiting for approval | Run the app for 10 minutes by voice alone: every command, navigation, question, approval, memo and dictation is reachable by voice and covered by tests (fakes in CI, real Whisper/Kokoro/Silero round trips with `UNIVERSE_TEST_VOICE_MODELS`); the 10-minute session itself needs the owner's mic | [PHASE-7](../PHASE-7.md), [ADR-0016](../adr/0016-phase-7-voice.md), [proposal](../proposals/phase-7-consent.md) |
| 8 Vision | Next | "Look at this error" returns a correct explanation and a handoff to Forge or Builder | SPEC §25 |

**Test suites after the full sweep** (2026-10-23, branch `745bfe2`; all green; Electron tests under `xvfb-run`):
- **pytest:** 407 passed, 8 skipped (7 real-voice-model tests that need `UNIVERSE_TEST_VOICE_MODELS`, which pass
  7 of 7 with the models; 1 Windows-only). Where `ollama` is on PATH the real-model tests run too; on a slow
  machine with a cold model the chat test's 60 s reply deadline can run out.
- **Vitest:** 218 (ui, desktop, scripts and design-tokens projects).
- **Playwright Electron:** 25 of 25 (app, safe-mode and the 50k universe suite).
- **Static:** eslint `--max-warnings=0`, prettier, typecheck, ruff, ruff format, pyright and both generated-file
  checks clean (`pnpm check` now runs all of them).
- **With the sweep-fixes patch applied:** see the proposal's "What was run".

## 4. What exists today

**Shell and HUD (Phases 1, 4)**
- Electron 44 app on design tokens: glass HUD, top bar with status chips, consent indicators, activity ribbon,
  side panels, keyboard shortcuts and accessibility options.
- Safe-mode page and tray.
- One-command start: `pnpm dev`.

**Core and reliability (Phases 1, 1.5)**
- FastAPI Core, WebSocket event hub and event bus with a persisted catalog.
- Structured logs and error capture from every process.
- A standard-library-only supervisor: restarts with backoff, last-known-good, safe mode.
- Hardware detection with model recommendations; Ollama management.

**Vault and recall (Phase 2)**
- Plain files on disk in open formats, with sidecars; three SQLite databases plus LanceDB vectors.
- An ingest pipeline with a crash-safe job queue, workers and a performance governor.
- Extraction, OCR and thumbnails.
- Hybrid search (keyword plus meaning).
- A global command bar (`Ctrl+Space`) with quick capture, clipboard capture and drag-drop.
- Watched folders, encrypted restic backups, trash and purge.
- 2D grid and list views.

**Agent engine (Phase 3)**
- **Agents:** YAML-defined, with a custom agent loop on the OpenAI-compatible API, tools and permission tiers.
- **Approvals:** a tray where you approve what agents want to do; untrusted content marks a task "tainted"
  and forces approvals.
- **Tracking:** task traces, memory you approve, a minimal MCP client, a model router.
- **Safety:** a hash-chained audit log, budget caps, a kill switch (`Ctrl+Alt+Shift+K`) and a policy engine
  (protected).

**Universe (Phase 4)**
- **The 3D universe on real data:**
  - notes are stars, photos planets, songs pulsars, code space stations and projects galaxies;
  - four layouts (Project, Semantic, Time, Graph) with animated transitions;
  - zoom levels Universe → Galaxy → System → Item;
  - smooth cursor-directed zoom, a minimap and breadcrumb, a time-travel slider;
  - galaxy dashboards with goals.
- **Viewers:** notes (Markdown, `[[wikilinks]]`, versions, conflict-safe saves), photos, PDFs, code, audio,
  video and documents.
- **Search lights up a constellation** and flies the camera to the results.
- **Quality presets** with automatic step-down, and a 2D Lite mode (sigma).
- **Neural layer:**
  - agent probes fly the link paths;
  - signal pulses travel along links;
  - link firings are recorded for Phase 9.
- **Agents panel → Roster:** synopses, stats, adding your own agents, turning agents off.

**Forge and Sentinel (Phase 5)**
- **Forge triage:** error, failed-job and bug-report triage, with dedup by fingerprint.
- **Forge fixes:** a test-first repro that must fail on the old code and pass with the fix. Fixes live in git
  worktrees on `forge/<id>` branches. Verification runs ruff, pyright, the full pytest suite, and eslint and
  Vitest, in a scrubbed environment.
- **Reviews:** Critic and Sentinel (a deterministic diff review: blocks protected-core edits, weakened tests,
  network code outside the egress gate, raised agent permissions, and text aimed at the reviewers).
- **Proposal cards:** the diff, the test report, both reviews, the risk and the rollback plan. At most 5 a
  day, and no apply tool exists.
- **Approval:** a native dialog in Electron main is the only way to apply. The supervisor re-checks
  everything, fast-forwards, tags, restarts Core, watches for 30 minutes and rolls back by itself on two
  crashes or safe mode. One-click rollback adds revert commits.
- **System Vitals:** services, loaded models, the job queue, errors, Forge and backups at a glance.

**Phase 6 — Research:**
- **Researcher agent** with `web.search` / `web.fetch` / `vault.save`; quick answers and deep cited reports saved
  to the vault. Every request goes through the egress gate; reading a page taints the task, so saving asks you.
- **Watchlists** (topics and pages re-checked on a schedule) and **"sent where"** (what left the machine).

**Phase 7 — Voice** (all local; ADR-0016):
- **Listening:** Whisper ONNX (tiny.en default), Silero VAD, push-to-talk (hold Space or the orb), a wake phrase
  ("Hey Universe", changeable) or continuous mode; barge-in stops speech the moment you talk over it.
- **Speaking:** Kokoro-82M, a voice per agent, answers spoken sentence by sentence as the model writes them.
- **What you can say:** navigation through the recall fast path (no LLM), panels and views, "read it", approvals
  ("approve" / "deny"; high risk and standing rules still need a click), dictation into any text field, memos.
- **Vault:** voice memos saved as items; every audio and video item gets a timestamped transcript.
- **Consent:** the mic is protected Electron-main code — off every launch, a native dialog to turn on, the kill
  switch closes it first (applied 2026-10-21).

**Not built yet** (by design, later phases):
- screen vision (8);
- the brain layer: consolidation, auto-linking, pathway strengthening, morning brief (9);
- creative studios (10);
- Forge self-upgrade (11);
- the Windows installer and wizard (12).

## 5. Architecture in one page

Full design: [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md). Decisions: [`docs/adr/`](../adr/).

```
Electron (apps/desktop)
├─ renderer (apps/ui): React 19, three.js / R3F universe, HUD, viewers. Sandboxed, strict CSP, app:// only.
└─ main: windows, tray, global hotkeys, command bar.
   [protected] kill switch, consent, native approval dialog, Forge apply/rollback.
      │ REST + WebSocket on 127.0.0.1, session token, Host/Origin checks
      ▼
Core (services/core, FastAPI): API, event bus, agent engine, search, memory, approvals, budget,
   audit writer, governor, egress gate, Forge.
   Workers (vault pipeline) run as Core's child processes.
      ▲ spawned and health-checked by
Supervisor (services/supervisor) [protected, stdlib only]: restarts, last-known-good, safe mode,
   applies and rolls back approved Forge releases.
Ollama (local LLMs, embeddings). Later: voice service, ONNX models service, SearXNG and a code sandbox.

Data, outside the repo, in the vault folder:
   type/yyyy/mm/ originals and Markdown notes with .universe.json sidecars
   .universe/universe.db, events.db, audit.db (SQLite, WAL), vectors/ (LanceDB), thumbs/, versions/
```

**Trust boundaries**
- Everything listens on loopback only.
- The renderer has no Node.
- All outbound traffic goes through `universe_common.egress`. A protected test fails on direct HTTP clients,
  and the e2e test fails on any non-loopback request.
- Forge's changes are applied only by the supervisor, after a native OS dialog. Neither Core nor the
  renderer (both code Forge can patch) can apply anything.

**The stack**

| Area | Choice |
| --- | --- |
| Languages | Python 3.12 (uv), TypeScript 6.0, Node 24, pnpm 12 |
| Desktop and UI | Electron 44, React 19, Tailwind, TanStack Query, Zustand |
| Universe rendering | three.js / R3F, with sigma for Lite mode |
| Backend | FastAPI, stdlib `sqlite3` with SQL migrations (no ORM), LanceDB, watchdog |
| Vault media | RapidOCR, pypdf, Pillow |
| Infrastructure | restic, keyring, structlog |
| Models | Ollama (OpenAI-compatible API), ONNX Runtime later |
| Tests and lint | pytest, Vitest, Playwright for Electron, ruff, pyright, ESLint, Prettier, pre-commit |

## 6. The agents

SPEC §8 plans fourteen specialists. Built so far (YAML in `agents/`, prompts in `agents/prompts/`):

| Agent | Access | What it does |
| --- | --- | --- |
| Core | write | The one you talk to. Plans, delegates to specialists, checks results, gives one answer. Always on. |
| Navigator | read | Moves you around the universe and flies the camera to things. |
| Librarian | write | Searches by keyword and meaning, reads and summarizes, always lists its sources. |
| Scribe | write | Writes notes, summaries and drafts. Every note is a new item, so nothing is overwritten. |
| Critic | read | Reviews other agents' output before you see it. Always on, can't change anything. |
| Forge | write, large model | *(Phase 5 patch)* Finds causes, writes a failing test, then the smallest fix, and proposes. Can never apply. |
| Sentinel | read | *(Phase 5 patch)* Safety review of every Forge change; its verdict is deterministic code. |

The owner can add their own agents in the Roster; they live in `<data dir>/agents/`. Still to come from
SPEC §8: Researcher, Composer, Curator, Builder, Strategist, Observer, Chronicler and others, each in its
phase.

## 7. Decisions

**The owner's** (verbatim, with dates): [`DECISIONS.md`](DECISIONS.md). In short:
- Phase 0 defaults accepted.
- Phases 1–4 approved, and the Phase 1.5, 3, 5 and 7 protected patches applied (5 and 7 on 2026-10-21).
- Neural pathways added to SPEC, with signal pulses and pathway-flying probes built.
- The agent roster with synopses.
- Portability to other AIs.

**Technical (ADRs):**

| ADR | Decision |
| --- | --- |
| [0001](../adr/0001-process-model-and-supervisor.md) | Electron shell, process model, a stdlib-only supervisor |
| [0002](../adr/0002-sqlite-job-queue.md) | Custom SQLite job queue instead of huey |
| [0003](../adr/0003-storage-layout.md) | Vault files, three SQLite files, LanceDB, no ORM |
| [0004](../adr/0004-custom-agent-loop.md) | Custom agent loop instead of PydanticAI |
| [0005](../adr/0005-model-runtimes.md) | Ollama plus an ONNX Runtime models service |
| [0006](../adr/0006-local-security-model.md) | Loopback, session token, egress gate, policy engine |
| [0007](../adr/0007-runtime-pins.md) | Python 3.12, TypeScript 6.0, Node 24 LTS |
| [0008](../adr/0008-license-policy.md) | License policy and flagged components (e.g. tinytag over GPL mutagen, Kokoro over GPL Piper) |
| [0009](../adr/0009-electron-privacy-hardening.md) | No outbound traffic from Chromium |
| [0010](../adr/0010-phase-2-vault-pipeline.md) | Workers under Core, Ollama embeddings, staged model roles |
| [0011](../adr/0011-phase-3-agent-engine.md) | Agent loop, approvals, protected policy, minimal MCP client |
| [0012](../adr/0012-phase-4-universe-renderer.md) | Scene data, layouts, renderer, Lite mode, viewers |
| [0013](../adr/0013-agents-you-add.md) | The roster, custom agents, turning agents off |
| [0014](../adr/0014-phase-5-forge-sentinel.md) | Forge and Sentinel v1: what's protected, verification, releases |

**Where the build departs from SPEC's defaults** (flagged as SPEC §26 asks; details in PHASE-0):
- custom job queue;
- custom agent loop;
- no ORM;
- RapidOCR instead of PaddleOCR;
- tinytag instead of mutagen;
- vision runs inside Core;
- a separate ONNX models service;
- mic capture and TTS in the renderer, for echo cancellation;
- Forge applies only through the supervisor after a native dialog.

## 8. Rules for whoever works on this

The full, binding list is in [`AGENTS.md`](../../AGENTS.md). The essentials:

1. **Protected core: never modify** the paths in [`protected-core.txt`](../../protected-core.txt):
   - the supervisor, Sentinel, `services/core/src/universe_core/protected/` and
     `apps/desktop/src/main/protected/`;
   - the safe-mode page, `agents/forge.yaml` and `agents/sentinel.yaml`;
   - `tests/protected/`, CI and pre-commit config, and the manifest itself.

   Instead, write a patch plus an explanation in `docs/proposals/`, tested in a scratch worktree. The owner
   applies it.
2. **Never disable, skip or weaken a test**, or lower a threshold. Every bug fix ships a regression test.
3. **Never delete or rewrite vault data.** Tests use temporary vaults.
4. **Licenses:** MIT, Apache-2.0, BSD, ISC, Zlib, OFL, MPL-2.0 (CC-BY-4.0 weights with attribution). Flag
   anything else with an alternative.
5. **No secrets** in code, config, logs or commits. Use the OS keyring.
6. **Outbound network only through the egress gate.**
7. **The supervisor imports only the standard library.**
8. **Consent stays off by default:** mic, screen and camera.
9. **Generated files** only via `pnpm tokens` and `pnpm gen:types`.
10. **One phase at a time.** Verify versions and licenses online before adding anything, write ADRs for
    decisions, and show real errors (never paper over failures with mocks).

## 9. Open items

**Waiting on the owner**
1. Apply [`docs/proposals/sweep-fixes-protected.patch`](../proposals/sweep-fixes-protected.md): 10 protected-core
   fixes (Sentinel blind spots, releases, safe mode, the kill switch). Until then, read a Forge proposal's file
   list yourself before approving it.
2. Apply [`docs/proposals/test-policy-clock.patch`](../proposals/test-policy-clock.md): one protected test
   assumed the machine had been up over a minute, and failed right after a boot.
3. Approve Phases 5, 6 and 7; install the voice models (Voice tab) and run the Phase 7 demo script on their own
   hardware (latency, echo cancellation).
4. Run `pnpm bench:universe` on their PC. The Phase 4 FPS budget: 60 FPS at 50k items in 3D on recommended
   hardware, 30 FPS at 10k in Lite on minimum hardware.
5. Send the Windows hardware report (`scripts/hardware-report.ps1`). The model loadouts stay unverified until
   then.
6. Fix GitHub Actions. Jobs never get a runner (they end in 2–3 s with no logs); a re-run after the 2026-10-21
   billing fix failed the same way. **Nothing has run on Windows yet.**
7. *(Decided 2026-10-14: leave it.)* `main` still holds the old Bolt landing page. The owner chose to keep all
   work on `claude/phase-0-delivery-zuqlfx` with no PR into `main` for now, so always use that branch.
8. Push the `pre-universe` tag (the build environment couldn't push tags):
   `git tag -a pre-universe e39257b -m "Bolt landing page" && git push origin pre-universe`.
9. Share the DevMind repository if its pieces should be reused.
10. On their PC, try real models: `nomic-embed-text` for meaning search, and a tool-calling model such as
   `qwen3:8b` for agents. Tune search relevance with `scripts/seed_vault.py bench`.

**Known limitations** (the newest first; each phase doc has the full list)
- **Uploads (found in the 2026-10-22 sweep):** FastAPI reads a multipart upload to temporary files before the
  session-token check runs, so a local program without the token can make Core spool a large body to disk
  before it is refused. Fixing it means parsing `/capture/files` by hand after auth (it changes the API schema);
  left for a decision.
- **Voice (Phase 7):**
  - Echo cancellation (Chromium's) and latency are unverified on the owner's hardware.
  - Whisper tiny.en mishears rare names; base.en is better and slower; vault names aren't yet given as hints.
  - The wake phrase is transcript-based (a Whisper run per utterance); our G2P is simpler than misaki's full
    pipeline. English only.
  - Transcribing MP3/M4A/video in the vault needs `ffmpeg` on PATH. No partial transcripts while you talk.
- **Forge (Phase 5):**
  - Verification isn't container-isolated (flagged, security). It doesn't yet run evals, perf benchmarks or
    the Electron suite.
  - Applying restarts Core only; UI fixes need a rebuild.
  - The watch checks crashes and safe mode, not error rates.
  - Nothing runs scheduled tests to file failures as issues; no perf-regression detection, no auto-apply
    toggle, no codebase galaxy yet.
  - No restic snapshot before apply.
- **Universe (Phase 4):**
  - FPS is unproven on a GPU, and Lite mode is slow in software rendering.
  - The Semantic layout is PCA plus k-means, not UMAP.
  - Planned views not built yet: table, timeline, kanban, map.
  - No network/offline pill yet; GPU picking is unconfirmed on Windows.
- **Agents (Phase 3):**
  - No real tool-calling model was run in the build environment.
  - Tasks don't survive a restart; delegation is one level deep.
  - Memory search is keyword-only.
  - MCP covers stdio servers only. MCP servers run with the owner's rights and their network isn't gated
    (flagged).
- **Vault (Phase 2):**
  - Not run on Windows.
  - The relevance cutoff is untuned for real embedders.
  - Ingest is CPU-bound by OCR (about 4 files/s here).
  - Transcription, image embeddings and the reranker are deferred.
  - `Ctrl+Space` can clash with East Asian input-method switchers.
- **Everywhere:** model registries (ollama.com, Hugging Face) were unreachable from the build environment, so
  real-model quality and latency are measured on the owner's PC.

## 10. Roadmap

SPEC §25, the remaining phases:

| Phase | Scope | Done when |
| --- | --- | --- |
| 8 Vision | Consented capture, VLM + OCR, "look at this", watch mode, exclusions, camera toggle | "Look at this error" returns a correct explanation and a handoff to Forge or Builder |
| 9 Brain layer | Memory UI, nightly consolidation, auto-linking, **neural pathways that strengthen with use**, resurfacing, morning brief, time travel, idea incubator, project dashboards, optional screen recall | The morning brief is generated from real data and the time slider replays history |
| 10 Creative studios | Composer audio tools, lyrics editor, hum-to-MIDI, Curator photo tools, map view, dedupe | A hummed voice memo becomes a tagged song idea with MIDI attached |
| 11 Forge v2 | Dependency upgrades, model scouting with local benchmarks, prompt A/B evals, perf proposals, workflow-to-skill proposals | Forge proposes and benchmarks one real model upgrade with numbers |
| 12 Ship | Windows installer, first-run wizard, encryption at rest, app lock, signed updates, performance and accessibility pass | A clean Windows install reaches a working universe through one wizard |

**Parked vision items** (owner's call to move them earlier):
- spreading activation (Phase 9);
- a Cluster zoom level (Phase 9);
- dream replay (Phase 9);
- visible working memory (Phase 9);
- system state as body signals.

**Future parking lot** (SPEC §29, out of scope until the owner says so):
- a phone companion;
- screen actions;
- VR/AR;
- multi-device sync;
- deep email and calendar;
- local fine-tuning;
- shareable galaxies.

## 11. The repository

- **GitHub:** `skyslasher001/web5`, **private**. The work branch is `claude/phase-0-delivery-zuqlfx`. `main`
  is the old Bolt site (an ancestor of the work branch, so the branch fast-forwards onto it).
- **History:** about 50 commits, one per meaningful step, with clear messages.

| Path | What |
| --- | --- |
| `SPEC.md` | The owner's requirements (every line is one) |
| `AGENTS.md` | Rules, commands, layout, current phase: the single source of truth for every AI |
| `docs/` | Architecture, phase records, ADRs, protected-core proposals, vision, handoff (this folder) |
| `apps/desktop` | Electron main, preload, safe-mode page |
| `apps/ui` | React HUD, universe, viewers, command bar |
| `services/core` | FastAPI Core: API, events, agents engine, Forge, migrations |
| `services/vault` | Vault storage, ingest, jobs, search, links, layouts |
| `services/agents` | Agent schema, loop, router, tool interface |
| `services/models` | Hardware detection, loadouts, Ollama client |
| `services/common` | Logging, egress gate, SQLite helpers, IDs |
| `services/supervisor` | The protected stdlib watchdog |
| `agents/` | Agent YAML and prompts |
| `packages/` | Design tokens, shared types (generated from the API) |
| `tests/` | `unit`, `integration`, `protected`, `e2e` (Playwright on Electron), `support` (fake Ollama and more) |
| `scripts/` | Seeders, benchmarks, hardware report, the handoff exporter |

## 12. Running and testing

| Task | Command |
| --- | --- |
| Install | `uv sync` and `pnpm install` (pnpm 12) |
| Run the app | `pnpm dev` (Linux as root: `pnpm dev -- --no-sandbox`) |
| Everything CI checks before its build | `pnpm check` (then `pnpm build` and the e2e tests, which it leaves out) |
| Python tests | `uv run pytest` (real-Ollama tests run when `ollama` is on `PATH`) |
| JS tests | `pnpm exec vitest run` |
| Electron e2e | `pnpm build && pnpm test:e2e` (no display: `xvfb-run -a pnpm test:e2e`) |
| Regenerate | `pnpm tokens` · `pnpm gen:types` |
| Universe benchmark | `pnpm bench:universe` |
| Export this handoff package | `pnpm handoff` |

Environment lessons (the slow tests, scratch worktrees, the real-Ollama tests under load):
[HANDOFF.md](../HANDOFF.md#environment-notes-learned-the-hard-way).

## 13. Measured numbers

Measured on a 4-core Linux build machine with no GPU (software rendering).

| What | Result | Budget |
| --- | --- | --- |
| Slowest search, 500-file vault (request to response) | 309 ms | < 1 s |
| Keyword search p95 / hybrid search p95 (inside Core) | 3 ms / 147 ms | < 100 / < 400 ms |
| Ingest | ~4 files/s (OCR is ~80%) | — |
| 2D list scrolling | 60 fps | ≥ 30 fps |
| Seeding 50,000 items | 34–44 s | — |
| App open → 50k items laid out | 17–22 s (the first page within a second) | — |
| Hybrid search at 50k | 0.36 s | < 400 ms |
| Camera flight to an item | planned 1200 ms, done in 1206–1328 ms | ≤ 1.2 s |
| 3D frame rate at 50k | 4–30 FPS in **software**; the GPU number must come from `pnpm bench:universe` | 60 FPS |
| Voice: Whisper tiny.en for a 2.5 s command (CPU) | 435 ms | — |
| Voice: Kokoro's first spoken sentence (CPU) | 646 ms | — |
| Voice: last word → first word back, navigation | ~1.2 s push-to-talk; ~1.8 s hands-free (0.7 s silence detection) | < 1.5 s |

## 14. Glossary

| Term | Meaning |
| --- | --- |
| Core | The FastAPI backend and also the orchestrator agent the owner talks to |
| Vault | The owner's data folder: plain files plus `.universe/` databases |
| Galaxy | A project; items orbit inside it |
| Item | Anything in the vault (note, photo, song, file, link, idea) |
| Probe | An agent's visible body in the universe |
| Pulse | Light travelling along a link when it fires |
| Pathway / synapse | A link between items; strengthens with use from Phase 9 |
| Forge | The self-repair agent: proposes tested fixes, never applies them |
| Sentinel | The safety reviewer of Forge's changes (deterministic code) |
| Protected core | Paths in `protected-core.txt` that no AI may edit; changes go to the owner as patches |
| Egress gate | The only module allowed to make outbound network requests |
| LKG | Last-known-good: the release the supervisor falls back to |
| Safe mode | A minimal page served by Electron when Core can't start; agents disabled |
| Tainted | A task that has read untrusted content; risky tools then need approval |
| Done when | Each phase's acceptance test from SPEC §25 |

## 15. Every document

| Document | What's in it |
| --- | --- |
| [`SPEC.md`](../../SPEC.md) | The requirements (29 sections) |
| [`AGENTS.md`](../../AGENTS.md) | Rules, commands, layout, current phase |
| [`README.md`](../../README.md) | Overview, setup on Windows, document index |
| [`docs/HANDOFF.md`](../HANDOFF.md) | How any AI picks up the work; how to get the project to an AI |
| [`docs/handoff/DECISIONS.md`](DECISIONS.md) | Every owner message and answer, verbatim |
| [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md) | The design, with "as built" notes |
| [`docs/VISION-neural-universe.md`](../VISION-neural-universe.md) | The neural universe and the voice receive chain |
| `docs/PHASE-0.md` … `docs/PHASE-7.md` | What each phase delivered, tests, limitations, what's next |
| [`docs/adr/`](../adr/) | 16 architecture decision records |
| [`docs/proposals/`](../proposals/) | Protected-core patches: 1.5, 3, 5 and 7 (microphone consent) applied; the review fixes applied; the test-policy clock fix waiting; the 6 SearXNG sidecar proposed |
| [`llms.txt`](../../llms.txt) | A short index for AI tools |
