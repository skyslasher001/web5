# UNIVERSE

A local-first Windows desktop app that works as a digital brain. Every project, note, idea, song, file, photo, link and conversation lives in one navigable 3D universe, run by a team of local AI agents. ("UNIVERSE" is a working name.)

## Status

**Phase 7 (Voice) is delivered** ([docs/PHASE-7.md](docs/PHASE-7.md)): talk to UNIVERSE and it answers in each agent's own voice, all on this computer — push-to-talk, a wake phrase or continuous listening, barge-in, voice navigation, approvals, dictation and voice memos. The microphone opens once you apply the consent patch ([docs/proposals/phase-7-consent.md](docs/proposals/phase-7-consent.md)). **Phase 6 (Research) is delivered** ([docs/PHASE-6.md](docs/PHASE-6.md)): a Researcher that answers from the live web, cites its sources, and can save a report to the vault — the first phase that goes online, defended by the egress gate and a taint→approval backstop. **Phase 5 (Forge + Sentinel v1) is delivered and waiting for review**, together with a protected-core patch for you to apply ([docs/proposals/phase-5-protected-core.md](docs/proposals/phase-5-protected-core.md)). Phases 1 (Foundation), 1.5 (fixes), 2 (Vault + Recall), 3 (Agent engine) and 4 (Universe interface) are delivered and approved. Phase 0 (Blueprint) was approved on 2026-10-12 with the default answers.

**Handing the project to another AI:** everything so far is in [docs/handoff/PROJECT-BRIEF.md](docs/handoff/PROJECT-BRIEF.md), and every decision you made is in [docs/handoff/DECISIONS.md](docs/handoff/DECISIONS.md). `pnpm handoff` builds a download package (start-here guide, text packs, source zip, git history) for any AI, and [docs/HANDOFF.md](docs/HANDOFF.md#getting-the-project-to-another-ai) says which file goes to which AI. All work is on the branch `claude/phase-0-delivery-zuqlfx`.

What works now: the Electron shell and HUD on the design tokens, streaming chat with the Core agent on a local Ollama model, the event bus and the three SQLite databases, structured logging and error capture, a watchdog supervisor that restarts Core and falls back to safe mode, hardware detection with model recommendations, the test suites, pre-commit hooks, CI on Windows and Linux, and `pnpm dev` as the one-command start. Details and the demo script are in [docs/PHASE-1.md](docs/PHASE-1.md). What Phase 1.5 fixed is in [docs/PHASE-1.5.md](docs/PHASE-1.5.md).

New in Phase 2: a vault you can drop files and folders into, quick capture and search from any app (`Ctrl+Space`), hybrid keyword + meaning search, grid and list views, watched folders, and encrypted restic backups. The 500-file "done when" passes with the slowest search at 309 ms. Details, setup and the demo are in [docs/PHASE-2.md](docs/PHASE-2.md).

New in Phase 3: Core orchestrates four specialists (Navigator, Librarian, Scribe, Critic) with tools on your vault, an approvals tray, permission rules, task traces, memory you approve, MCP tool servers, a hash-chained audit log, budget caps and a kill switch (`Ctrl+Alt+Shift+K`). *"Find my notes about X, summarize them, and link them to project Y"* works end to end. Details, setup and the demo are in [docs/PHASE-3.md](docs/PHASE-3.md).

New in Phase 4: the 3D universe on your own data. Notes are stars, photos planets, songs pulsars and projects galaxies. There are four layouts (Project, Semantic, Time, Graph) with animated transitions, zoom levels from the whole universe down to one item, viewers for notes (with `[[wikilinks]]` and versions), photos, PDFs, code, audio and video, galaxy dashboards, agent probes that fly to what they work on, search that lights up a constellation and flies the camera there, quality presets and a 2D Lite mode. A 50,000-item seed loads and searches; `pnpm bench:universe` measures the FPS budget on your machine. Details, setup and the demo are in [docs/PHASE-4.md](docs/PHASE-4.md). The Agents panel's Roster shows every agent with a synopsis and stats; you can add your own agents and turn agents off. A proposal for making the universe work like a brain is in [docs/VISION-neural-universe.md](docs/VISION-neural-universe.md).

New in Phase 5: Forge repairs UNIVERSE. Report a problem in the Forge panel (or let it pick up errors and failing background jobs), and Forge reproduces it with a failing test, fixes it in its own git worktree, runs lint, types and the test suites, and has Critic and Sentinel review it. The proposal card shows the diff, the tests and both reviews. Only Apply in a native dialog changes your code; the supervisor re-checks everything, watches the change for 30 minutes and rolls it back on its own if Core breaks, and System → Releases rolls it back in one click. The System panel's Vitals show services, loaded models, the queue, errors, Forge and backups at a glance. Details, setup and the demo are in [docs/PHASE-5.md](docs/PHASE-5.md).

New in Phase 7: Voice. Install the voice models from the Voice tab (Whisper, Kokoro and Silero, about 240 MB, hash-checked), turn voice on, and talk: hold Space (or the orb) to talk, or say "Hey Universe …", or switch to continuous mode. "Take me to Ember Wolf" flies there without touching an LLM; questions go to Core and the answer is spoken sentence by sentence as it's written, in the voice of whichever agent answers. Talk over it to interrupt. Agents read their approval requests out and you can answer "approve" or "deny" (high-risk ones still take a click). "Take a memo" records a voice memo that lands in the vault transcribed — and every audio and video file in the vault now gets a timestamped transcript. Nothing you say is stored unless you save a memo. The mic is off at every launch, only opens after a native dialog, and the kill switch closes it first; that consent code is protected, so it waits for you as a patch. Details in [docs/PHASE-7.md](docs/PHASE-7.md).

New in Phase 6: Research. The Research tab asks the live web — Quick for a fast cited answer, Deep for a cross-checked report saved to your vault. It plans its searches, reads the pages it picks, and cites every claim. Web pages are untrusted: the researcher quotes them, never obeys them, every request goes through the egress gate (the offline switch and kill switch block it, all of it logged), and because reading the web taints the task, saving a report asks you first. Watchlists re-run a topic or page and flag changes; "Sent where" shows exactly what left the machine. The default search needs nothing installed; the SearXNG container is an opt-in proposal. Details in [docs/PHASE-6.md](docs/PHASE-6.md).

## Setup (Windows 10/11)

Install once:

| Tool | Install | Why |
| --- | --- | --- |
| Git | `winget install Git.Git` | source control (and Forge's last-known-good) |
| Node.js 24 LTS (22.12+ works) | `winget install OpenJS.NodeJS.LTS` | UI and Electron tooling |
| pnpm 12 | `npm install -g pnpm@12.11.2` | JS workspace (Corepack ≤ 0.36 can't launch pnpm 12, so install it with npm) |
| uv | `winget install astral-sh.uv` | Python 3.12 and every Python dependency (no system Python needed) |
| Ollama | `winget install Ollama.Ollama` | local models; UNIVERSE starts it if it isn't running |

Then, from the repo root:

```powershell
uv sync                      # Python 3.12 + services (creates .venv)
pnpm install                 # JS deps, downloads Electron
ollama pull gemma4:e4b       # or the model the System panel recommends for your hardware
pnpm dev                     # starts everything: Vite, Electron → supervisor → Core (+ Ollama)
```

Your data lives in `.dev/vault` while developing. To use a real vault, copy `.env.example` to `.env` and set `UNIVERSE_VAULT_DIR` (for example `D:\UniverseVault`).

Optional: `uv run pre-commit install` to run the same lint, format and type checks on every commit.

## Commands

| Command | What it does |
| --- | --- |
| `pnpm dev` | One-command dev start (hot-reloading UI) |
| `pnpm start` | Production-like run: built UI served over `app://` |
| `pnpm build` | Design tokens, UI bundle, Electron main/preload |
| `pnpm test` | Python tests (pytest) + JS unit tests (Vitest) |
| `pnpm test:e2e` | Electron end-to-end tests with Playwright (`pnpm build` first) |
| `pnpm check` | Everything CI runs: lint, format, types, tests |
| `pnpm gen:types` | Regenerate `packages/shared-types` from the backend's OpenAPI schema |
| `pnpm tokens` | Regenerate CSS/TS from `packages/design-tokens/tokens.json` |
| `pnpm bench:universe` | Seeds 50k items and measures frame rates per quality preset and layout against the SPEC budget (`pnpm build` first) |
| `powershell -ExecutionPolicy Bypass -File scripts\hardware-report.ps1` | Hardware report for model planning |

## Layout

```
apps/desktop      Electron main + preload (supervisor launcher, safe-mode page, app:// protocol)
apps/ui           React HUD + 3D universe
services/core     FastAPI: API, WebSocket hub, event bus, chat, vault runtime, agent engine, memory, MCP, audit log
services/agents   agent loop, tool interface, tool-calling provider, model router
services/models   hardware detection, model recommendations, Ollama client
services/common   config, ids, logging, error capture, egress gate, SQLite helpers
services/supervisor  stdlib-only watchdog: restarts, last-known-good, safe mode
agents/           agent YAML + prompts (Core, Navigator, Librarian, Scribe, Critic)
packages/         design tokens, shared types
tests/            unit, integration, protected-core guards, Electron e2e
```

## Documents

| Document | What's in it |
| --- | --- |
| [SPEC.md](SPEC.md) | Requirements: the master build prompt |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Architecture, tech decisions, data model, API/events, UI concept, Forge safety design |
| [docs/VISION-neural-universe.md](docs/VISION-neural-universe.md) | Proposal: the universe as a neural network (pathways that strengthen with use, signal pulses), and the voice receive chain |
| [docs/PHASE-6-PLAN.md](docs/PHASE-6-PLAN.md) | Phase 6 (Research) prep: scope, verified dependencies, build order, test strategy, and the egress/privacy/injection review (ADR-0015) |
| [docs/IDEAS-smooth-and-intelligent.md](docs/IDEAS-smooth-and-intelligent.md) | Ranked ideas toward a smoother, more intelligent universe, mapped to phases |
| [docs/handoff/PROJECT-BRIEF.md](docs/handoff/PROJECT-BRIEF.md) | Everything about the project so far in one document: vision, status, features, architecture, decisions, rules, open items, roadmap |
| [docs/handoff/DECISIONS.md](docs/handoff/DECISIONS.md) | Every owner message and decision, verbatim, with what was done |
| [docs/HANDOFF.md](docs/HANDOFF.md) | Working on UNIVERSE with any AI assistant (Claude Code, Codex, Copilot, Cursor, Windsurf, Cline, Gemini CLI, Aider): the start prompt, how to work and deliver a phase, environment notes, which instruction file each tool reads |
| [docs/PHASE-6.md](docs/PHASE-6.md) | Phase 6 delivery: Research (live-web search/fetch/extract through the egress gate, cited answers, deep reports to the vault, injection defense, watchlists, "sent where"); setup, demo, limitations |
| [docs/PHASE-7.md](docs/PHASE-7.md) | Phase 7 delivery: Voice (Whisper/Kokoro/Silero on ONNX Runtime, wake phrase, modes, barge-in, voice navigation, approvals and dictation by voice, memos, vault transcription); setup, demo, limitations |
| [docs/PHASE-5.md](docs/PHASE-5.md) | Phase 5 delivery: Forge (triage, test-first fixes in worktrees, verification, proposals), Sentinel, apply/watch/rollback, System Vitals; setup, demo script, known limitations |
| [docs/PHASE-4.md](docs/PHASE-4.md) | Phase 4 delivery: 3D universe, layouts, viewers, dashboards, quality presets, Lite mode; setup, demo script, measured numbers, known limitations |
| [docs/PHASE-3.md](docs/PHASE-3.md) | Phase 3 delivery: agent engine, approvals, memory, MCP, audit, budget, kill switch; setup, demo script, known limitations |
| [docs/PHASE-2.md](docs/PHASE-2.md) | Phase 2 delivery: vault, search, command bar, backups; setup, demo script, measured numbers, known limitations |
| [docs/PHASE-1.5.md](docs/PHASE-1.5.md) | Phase 1.5: bugs fixed, real-Ollama verification, open limitations |
| [docs/proposals/](docs/proposals/) | Changes to protected core, proposed for the owner to apply (with their status) |
| [docs/PHASE-1.md](docs/PHASE-1.md) | Phase 1 delivery: setup, demo script, tests, measured numbers, known limitations |
| [docs/PHASE-0.md](docs/PHASE-0.md) | Phase 0 delivery and the answers to its questions |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [AGENTS.md](AGENTS.md) | Rules for AI coding assistants and Forge |

The previous Bolt landing page that lived in this repo is preserved in git history (tag `pre-universe`).
