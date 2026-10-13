# UNIVERSE

A local-first Windows desktop app that works as a digital brain. Every project, note, idea, song, file, photo, link and conversation lives in one navigable 3D universe, run by a team of local AI agents. ("UNIVERSE" is a working name.)

## Status

**Phase 3 (Agent engine) is delivered and waiting for review**; its protected-core patch is applied. Phases 1 (Foundation), 1.5 (fixes) and 2 (Vault + Recall) are delivered and approved. Phase 0 (Blueprint) was approved on 2026-10-12 with the default answers.

What works now: the Electron shell and HUD on the design tokens, streaming chat with the Core agent on a local Ollama model, the event bus and the three SQLite databases, structured logging and error capture, a watchdog supervisor that restarts Core and falls back to safe mode, hardware detection with model recommendations, the test suites, pre-commit hooks, CI on Windows and Linux, and `pnpm dev` as the one-command start. Details and the demo script are in [docs/PHASE-1.md](docs/PHASE-1.md). What Phase 1.5 fixed is in [docs/PHASE-1.5.md](docs/PHASE-1.5.md).

New in Phase 2: a vault you can drop files and folders into, quick capture and search from any app (`Ctrl+Space`), hybrid keyword + meaning search, grid and list views, watched folders, and encrypted restic backups. The 500-file "done when" passes with the slowest search at 309 ms. Details, setup and the demo are in [docs/PHASE-2.md](docs/PHASE-2.md).

New in Phase 3: Core orchestrates four specialists (Navigator, Librarian, Scribe, Critic) with tools on your vault, an approvals tray, permission rules, task traces, memory you approve, MCP tool servers, a hash-chained audit log, budget caps and a kill switch (`Ctrl+Alt+Shift+K`). *"Find my notes about X, summarize them, and link them to project Y"* works end to end. Details, setup and the demo are in [docs/PHASE-3.md](docs/PHASE-3.md).

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
| [docs/PHASE-3.md](docs/PHASE-3.md) | Phase 3 delivery: agent engine, approvals, memory, MCP, audit, budget, kill switch; setup, demo script, known limitations |
| [docs/PHASE-2.md](docs/PHASE-2.md) | Phase 2 delivery: vault, search, command bar, backups; setup, demo script, measured numbers, known limitations |
| [docs/PHASE-1.5.md](docs/PHASE-1.5.md) | Phase 1.5: bugs fixed, real-Ollama verification, open limitations |
| [docs/proposals/](docs/proposals/) | Changes to protected core, proposed for the owner to apply (with their status) |
| [docs/PHASE-1.md](docs/PHASE-1.md) | Phase 1 delivery: setup, demo script, tests, measured numbers, known limitations |
| [docs/PHASE-0.md](docs/PHASE-0.md) | Phase 0 delivery and the answers to its questions |
| [docs/adr/](docs/adr/) | Architecture decision records |
| [AGENTS.md](AGENTS.md) | Rules for AI coding assistants and Forge |

The previous Bolt landing page that lived in this repo is preserved in git history (tag `pre-universe`).
