# AGENTS.md — rules for AI coding assistants and Forge

UNIVERSE is a local-first Windows desktop "digital brain": Electron + React UI, Python/FastAPI services, SQLite + LanceDB, local models via Ollama.

## Read first

1. [`SPEC.md`](SPEC.md): the requirements. Every line is a requirement.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the design. Follow it, or change it explicitly with an ADR.
3. [`docs/PHASE-3.md`](docs/PHASE-3.md) (and [`PHASE-2.md`](docs/PHASE-2.md), [`PHASE-1.md`](docs/PHASE-1.md), [`PHASE-1.5.md`](docs/PHASE-1.5.md)): what exists now, what was fixed, open limitations, what's next.

**Current phase:** Phase 3 (Agent engine) delivered 2026-10-13, waiting for the owner's review. Its protected-core patch ([`docs/proposals/phase-3-protected-core.md`](docs/proposals/phase-3-protected-core.md)) is waiting for the owner to apply; until then agents chat without tools and the engine tests skip. Phases 1, 1.5 and 2 are approved, and the Phase 1.5 protected-core patch is applied.

## How to work

- One phase at a time (SPEC §25). A phase ends with runnable code, tests, setup steps, a demo script, known limitations, and what's next (as a `docs/PHASE-N.md`).
- Simple over clever. No abstractions beyond the plugin interfaces.
- Verify current versions, models and licenses online before adding or upgrading anything. Don't rely on memory.
- Record decisions as ADRs in `docs/adr/` (template in `docs/adr/README.md`). Flag in 1–2 lines anything that materially changes cost, privacy, security or architecture.
- When something fails, show the real error and fix it. Never paper over failures with mocks. Test doubles are only for external services we can't run in CI (`tests/support/fake_ollama.py`).
- Keep this file and `CLAUDE.md` current when commands, layout or rules change.

## Hard rules

- **Protected core — never modify** the paths in [`protected-core.txt`](protected-core.txt): the supervisor, `services/core/src/universe_core/protected/` (audit writer; later the permission engine, consent, budget caps, kill switch), Sentinel, `apps/desktop/src/main/protected/`, the safe-mode page, `agents/forge.yaml`, `agents/sentinel.yaml`, `tests/protected/`, CI and pre-commit config, and the manifest itself. For these, write a proposal for the owner to apply: a patch plus an explanation in `docs/proposals/`, tested in a scratch worktree.
- **Never disable, skip or weaken a test**, loosen an assertion, or lower a threshold to make something pass. Every bug fix ships a regression test.
- **Never delete or rewrite vault data.** Tests use temporary vaults (`tmp_path`), never a real vault path.
- **Licenses:** only MIT / Apache-2.0 / BSD / ISC / Zlib / OFL / MPL-2.0 (plus CC-BY-4.0 weights with attribution). Flag GPL, AGPL or non-commercial items with an alternative before adopting them. See [ADR-0008](docs/adr/0008-license-policy.md).
- **No secrets** in code, config, logs or commits. Use the OS credential store (`keyring`). Register any token with `universe_common.log.register_secret` so logs redact it.
- **Outbound network only through the egress gate** (`universe_common.egress`). `tests/protected/test_invariants.py` fails on direct HTTP clients. The Electron e2e test fails on any non-loopback request.
- **The supervisor imports only the standard library.** It runs with `python -I -S`.
- **Consent stays off by default:** mic, screen and camera. Nothing captured is stored unless the owner says so.
- **Generated files** (`packages/design-tokens/generated/`, `packages/shared-types/src/{api,events}.ts`, `openapi.json`) are never edited by hand: run `pnpm tokens` / `pnpm gen:types`.

## Commands

| Task | Command |
| --- | --- |
| Install | `uv sync` and `pnpm install` (pnpm 12: `npm i -g pnpm@12.11.2`) |
| Run the app | `pnpm dev` (on Linux as root: `pnpm dev -- --no-sandbox`) |
| Everything CI checks | `pnpm check` |
| Python tests / lint / types | `uv run pytest` · `uv run ruff check` · `uv run ruff format --check` · `uv run pyright` |
| Test against a real Ollama | runs inside `uv run pytest` when `ollama` is on `PATH` or `UNIVERSE_TEST_OLLAMA` points at it; skipped otherwise |
| JS tests / lint / types | `pnpm exec vitest run` · `pnpm exec eslint .` · `pnpm exec prettier --check .` · `pnpm -r typecheck` |
| Electron e2e | `pnpm build && pnpm test:e2e` (Linux without a display: `xvfb-run -a pnpm test:e2e`) |
| Regenerate | `pnpm tokens` · `pnpm gen:types` |
| Phase 3 done-when | `uv run pytest tests/integration/test_agent_engine.py` and the e2e run (both need the protected-core patch; skipped without it) |
| Phase 2 done-when | `uv run pytest tests/integration/test_done_when.py -s` (500 files, ~3 min) · demo data: `uv run python scripts/seed_vault.py generate <empty folder>` then `bench <manifest> --key uk_…` |

## Layout

- `services/core` — FastAPI app (`app.py`), REST (`api.py`, `vault_api.py`, `vault_admin_api.py`; every handler `async def`, a test enforces it), WebSocket hub (`ws.py`), event bus + catalog (`events.py`), chat (`chat.py`), vault runtime (`vault_runtime.py`: the vault DB thread, worker processes, governor), backups (`backups.py`), migrations (`migrations/<db>/NNNN_name.{up,down}.sql`, never edit an applied one).
- `services/vault` — the vault (ADR-0010): file types and storage layout, ingest, job queue (`jobs.py`), governor, pipeline stages and handlers, worker process (`worker.py`), extraction, OCR and thumbnails (`media.py`), LanceDB vectors, query parser and hybrid search, trash/purge, folder watcher, restic backups. Vault DB work in Core goes through `ctx.vdb.run`.
- `services/agents` — agent YAML schema (`registry.py`), streaming tool-calling provider, model router (`resolve(tier, needs_tools=…)`), the agent loop (`runtime.py`: steps, guardrails, taint, the `Policy` protocol) and the tool interface (`tools.py`). No Core or database imports.
- Agent engine in Core — `agent_engine.py` (tasks, steps, approvals, delegation, Critic review, usage ledger), `agent_tools.py` (built-in tools), `memory.py`, `mcp_client.py` (minimal stdio MCP client + manager), `agents_api.py` (REST). The policy engine, permission rules, budget caps and kill switch live in `protected/` and load through `context.load_safety`; absent, `NO_SAFETY` applies and agents chat without tools.
- `agents/` — one YAML per agent (core, navigator, librarian, scribe, critic; plus the protected forge/sentinel) and prompts in `agents/prompts/`.
- `services/models` — hardware detection, loadouts (`loadouts.yaml`), Ollama client.
- `services/common` — config helpers, UUIDv7, logging, error capture, egress gate, SQLite helpers (incl. `snapshot`), parent watch (`orphan.py`), `ApiModel` (base class for API models: fields the server always sends become required in the generated types).
- `services/supervisor` — watchdog (stdlib only); entry `run_supervisor.py`.
- `apps/desktop` — Electron main (`src/main`: window, command bar window + global shortcut, tray, clipboard capture, vault path checks), preload, safe-mode page. `apps/ui` — React HUD (`hud/`: incl. `AgentsPanel` tasks/traces/memory, `SafetyPanel` kill switch/budget/rules/MCP/audit, `ApprovalsTray`, `KillSwitch`), 2D grid/list (`views2d/`), command bar app (`command/`, served at `#command-bar`), and the 3D scene. Item queries refresh through `lib/queryClient.ts`; agent-engine queries refresh from events (`refreshForEvent`).
- `tests/unit`, `tests/integration`, `tests/protected`, `tests/e2e`, `tests/support` (fake Ollama with concept embeddings and a scripted tool-calling model, an MCP demo server, fake Core, tiny GGUF model writer, test file writers, the 500-file seed generator, an in-memory keyring).
- `docs/proposals/` — protected-core changes proposed to the owner (patch + explanation + status).
