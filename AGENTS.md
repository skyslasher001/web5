# AGENTS.md — rules for AI coding assistants and Forge

UNIVERSE is a local-first Windows desktop "digital brain": Electron + React UI, Python/FastAPI services, SQLite + LanceDB, local models via Ollama.

## Read first

1. [`SPEC.md`](SPEC.md): the requirements. Every line is a requirement.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the design. Follow it, or change it explicitly with an ADR.
3. [`docs/PHASE-1.md`](docs/PHASE-1.md): what exists now, known limitations, what's next.

**Current phase:** Phase 1 (Foundation) has been delivered and is **awaiting approval**. Don't start Phase 2 work until the owner approves.

## How to work

- One phase at a time (SPEC §25). A phase ends with runnable code, tests, setup steps, a demo script, known limitations, and what's next (as a `docs/PHASE-N.md`).
- Simple over clever. No abstractions beyond the plugin interfaces.
- Verify current versions, models and licenses online before adding or upgrading anything. Don't rely on memory.
- Record decisions as ADRs in `docs/adr/` (template in `docs/adr/README.md`). Flag in 1–2 lines anything that materially changes cost, privacy, security or architecture.
- When something fails, show the real error and fix it. Never paper over failures with mocks. Test doubles are only for external services we can't run in CI (`tests/support/fake_ollama.py`).
- Keep this file and `CLAUDE.md` current when commands, layout or rules change.

## Hard rules

- **Protected core — never modify** the paths in [`protected-core.txt`](protected-core.txt): the supervisor, `services/core/src/universe_core/protected/` (audit writer; later the permission engine, consent, budget caps, kill switch), Sentinel, `apps/desktop/src/main/protected/`, the safe-mode page, `agents/forge.yaml`, `agents/sentinel.yaml`, `tests/protected/`, CI and pre-commit config, and the manifest itself. For these, write a proposal (diff + explanation) for the owner to apply.
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
| JS tests / lint / types | `pnpm exec vitest run` · `pnpm exec eslint .` · `pnpm exec prettier --check .` · `pnpm -r typecheck` |
| Electron e2e | `pnpm build && pnpm test:e2e` (Linux without a display: `xvfb-run -a pnpm test:e2e`) |
| Regenerate | `pnpm tokens` · `pnpm gen:types` |

## Layout

- `services/core` — FastAPI app (`app.py`), REST (`api.py`), WebSocket hub (`ws.py`), event bus + catalog (`events.py`), chat (`chat.py`), migrations (`migrations/<db>/NNNN_name.{up,down}.sql`, never edit an applied one).
- `services/agents` — agent YAML schema (`registry.py`), streaming provider, model router.
- `services/models` — hardware detection, loadouts (`loadouts.yaml`), Ollama client.
- `services/common` — config helpers, UUIDv7, logging, error capture, egress gate, SQLite helpers.
- `services/supervisor` — watchdog (stdlib only); entry `run_supervisor.py`.
- `apps/desktop` — Electron main (`src/main`), preload, safe-mode page. `apps/ui` — React HUD and the 3D scene.
- `tests/unit`, `tests/integration`, `tests/protected`, `tests/e2e`, `tests/support` (fake Ollama, fake Core).
