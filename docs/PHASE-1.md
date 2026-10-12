# Phase 1 — Foundation delivery

Status: **delivered 2026-10-12, awaiting your go-ahead for Phase 2.**

SPEC §25 "done when": *I launch the app, chat with streaming replies, kill the backend and watch it auto-restart, and all tests pass.* Each part is covered by an automated end-to-end test against the real Electron app (`tests/e2e/app.spec.ts`), and the demo script below walks you through it by hand.

## What was built

| SPEC §25 item | Where | Notes |
| --- | --- | --- |
| Monorepo | root | pnpm 12 workspaces (`apps/*`, `packages/*`) and a uv workspace (`services/*`). The Bolt landing page is removed (tag `pre-universe`). |
| Electron shell on the design tokens, base HUD frame | `apps/desktop`, `apps/ui`, `packages/design-tokens` | Sandboxed renderer, `app://` protocol with strict CSP, frameless window. HUD: top bar + command palette, status cluster, agent dock, Context/System panel, activity ribbon, chat orb, zen mode, and a 3D starfield with the Core and your four seed galaxies. |
| FastAPI + WebSocket streaming chat to a local model via Ollama | `services/core`, `services/agents` | Thin OpenAI-compatible streaming client (no SDK) going through the egress gate. Single-use WS tickets. Reconnect with gap-free replay (`since_seq`). |
| SQLite | `services/core/.../migrations` | `universe.db`, `events.db`, `audit.db` (append-only, hash-chained) in `<vault>/.universe/`, with tested up/down migrations. |
| Core agent | `agents/core.yaml`, `agents/prompts/core.md` | Validated YAML definition (SPEC §8 fields). Conversation history kept in a char budget. Honest about what it can't do yet. |
| Event bus | `services/core/.../events.py` | Full event catalog from ARCHITECTURE.md §5.3. Persisted vs live events. Replay and tail. |
| Structured logging + error capture | `services/common` | JSON logs per service with secret redaction. Errors from Core, the renderer and Electron main are grouped by fingerprint in `errors` and emitted as `error.raised` (Forge's future input). |
| Supervisor with safe mode | `services/supervisor` | Stdlib only, runs `python -I -S` on the base interpreter. Health checks, restart with backoff, boot-failure counting, safe mode after 2 failed boots (persisted), last-known-good commit promotion + worktree, control API, Windows Job Object, stdin-EOF shutdown. Static safe-mode page in Electron. |
| Test harness + pre-commit | `tests/`, `.pre-commit-config.yaml` | pytest (unit, integration, protected-core guards), Vitest, Playwright for Electron. Local pre-commit hooks pinned to the lockfiles. |
| Git | repo | Plus CI on `windows-latest` and `ubuntu-latest` (`.github/workflows/ci.yml`). |
| Hardware detection + model recommendations | `services/models` | CPU/RAM/disks/battery via psutil, NVIDIA via NVML, other Windows GPUs via the display-adapter registry (real VRAM beyond 4 GB). Tier → loadout from `loadouts.yaml`. Shown in the System panel with copyable `ollama pull` commands. |
| One-command dev start | `scripts/dev.mjs` | `pnpm dev`. `pnpm start` runs the built UI. |

Also in place for later phases: `protected-core.txt` (with tests that keep it honest), the egress gate (only loopback traffic so far, everything else audited or blocked), the audit writer, and the generated shared types (`pnpm gen:types`, drift-checked in CI).

## Setup

See [README → Setup](../README.md#setup-windows-1011). In short: install Git, Node 24, pnpm 12 (`npm i -g pnpm@12.11.2`), uv and Ollama, then `uv sync`, `pnpm install`, `ollama pull <model>`, `pnpm dev`.

Which model? Open **System** (press `S`) after the first start: it lists the tier for your hardware and the suggested tags. The shortlist is from web research on 2026-10-12 and hasn't been checked against model cards yet (see limitations).

## Demo script (≈5 minutes)

1. **Launch.** `pnpm dev`. The window opens on deep space: the Core star with four galaxies (Ember Wolf Acquisitions, DevMind, Algo trading bot, UNIVERSE). The top-right shows **Core online** and the chat model name. If it says *no model*, follow the hint in **System → Chat model**.
2. **Look around.** Click a galaxy (in space or in the Context list) to see it in the right panel. The breadcrumb follows. Press `Z` for zen mode and `Esc` to come back. Press `Ctrl+K` for the command palette.
3. **Chat.** Press `C` (or click the orb). Ask *"What can you do right now?"*. Tokens stream in; the orb spins while Core thinks and replies; the reply shows the model and time to first token. Press **Stop** mid-reply to cancel (the partial reply is kept). History (clock icon) reopens past conversations.
4. **Kill the backend.** Either `Ctrl+K` → **Simulate a Core crash**, or the real way: Task Manager → Details → end the `python.exe` whose command line ends in `-m universe_core` (its pid is in **System → Core**). Watch the top-right switch to *Reconnecting…* and the banner show the supervisor restarting Core, then return to **Core online**, usually within 2 seconds. The activity ribbon logs *Core restarted after a crash (exit …)*. **System → Services** counts the restart, and chatting works again with history intact.
5. **Safe mode (optional).** Close the app. Occupy Core's port (for example `uv run python -m http.server 47821 --bind 127.0.0.1` in another terminal) and launch again. Core fails twice → safe mode → fails again → the static safe-mode page explains what happened (*address already in use*) and shows the logs. Stop the blocker, click **Try a normal start**, then **Back to UNIVERSE**.
6. **Hardware.** **System** shows your CPU, RAM, GPU/VRAM, the tier and the recommended models.
7. **Tests.** `pnpm check` (lint, types, all unit and integration tests), then `pnpm build && pnpm test:e2e`.

## Tests

| Suite | Count | Covers |
| --- | --- | --- |
| pytest (`uv run pytest`) | 92 | ids, migrations (up/down for every DB), event bus, audit chain + append-only triggers, error grouping, egress gate, agent YAML validation, tier thresholds, hardware probe, settings, router + streaming provider against a fake Ollama over real HTTP, the full Core API (auth, Host/Origin checks, CORS, WS tickets, streaming, cancel, failures, safe mode, audit), the supervisor state machine (crash restart, health restart, safe mode, LKG worktree, control API auth), and a real `python -I -S` supervisor process + real Core: kill → restart |
| Vitest (`pnpm exec vitest run`) | 25 | chat/agent reducers, WebSocket reconnect + dedupe, REST errors, formatting, Python path resolution, `app://` path safety + CSP, supervisor line protocol, design-token contrast (WCAG AA) and drift |
| Playwright Electron (`pnpm test:e2e`) | 6 | boot to a live HUD with seed galaxies, streamed chat, kill Core → auto-restart → chat again, System panel, **no request leaves the machine** (Chromium net log has loopback only), safe mode end to end |

All of the above passed locally (Linux, Python 3.12.13, Node 22). CI runs the same on Windows. The first Windows run happens when this branch is pushed (see limitations).

## Measured numbers (this build environment: 4-core Xeon VM, no GPU, Linux, software WebGL)

| SPEC §24 budget | Target | Measured | Notes |
| --- | --- | --- | --- |
| App shell usable after launch | < 3 s | Core healthy 0.8 s after spawn; HUD *Core online* in ~3.8 s from process launch under Playwright | The UI shell paints before three.js loads (lazy chunk). Will re-measure on your PC. |
| Idle RAM, no models loaded | < 1 GB | ~870 MB summed RSS (Electron processes, supervisor 27 MB, Core 63 MB) | Upper bound: shared pages are double-counted. The GPU process is heavier with software WebGL. Watch this in Phase 4. |
| Backend auto-restart | — | ~1.3 s (0.5 s backoff + 0.8 s boot) | From kill to healthy. The UI reconnects on the next attempt. |
| Chat first streamed token | < 1 s | not measurable here | No real model in this environment; the fake model answers in ~5 ms. Measure on your hardware. |

## Decisions made during Phase 1

- **Thin streaming client instead of the `openai` SDK.** About 60 lines over the egress-gated httpx client: one less dependency, and every model call is visibly gated. ADR-0005 updated.
- **CORS for the app's own origins only.** The renderer runs at `app://universe` and talks to `http://127.0.0.1:47821`, so CORS must allow exactly that origin (plus Vite in dev). Every other origin is still rejected by the Host/Origin guard. ADR-0006 corrected.
- **Chromium privacy hardening** ([ADR-0009](adr/0009-electron-privacy-hardening.md)): Electron's spellchecker was downloading dictionaries from Google at startup. It's now disabled at session creation, along with Chromium's background networking and component updates. An e2e test fails if any non-loopback request appears in the net log.
- **Clients may name a new conversation** (a UUID) so its streamed events match immediately.
- **Tertiary text color** raised from `#7C88A8` to `#808CAC`: the contrast test found 4.48:1 on the lightest surface (needs 4.5).
- **Core always sends warnings and errors to stderr** (captured by the supervisor), so the safe-mode page shows the real cause.
- **pnpm 12** uses `allowBuilds` (Electron, esbuild) and a minimum-release-age policy; the exact pins are listed in `pnpm-workspace.yaml`.

## Known limitations

- **Not yet run on Windows.** This environment is Linux. Windows-specific code (Job Object, registry GPU probe, `CREATE_NO_WINDOW`, title-bar overlay) is written and type-checked, and CI is set up to run everything on `windows-latest`, but it has not executed on Windows yet.
- **CI didn't start on GitHub.** The first run of `.github/workflows/ci.yml` ended in `startup_failure` before any job ran. The workflow passes `actionlint` 1.7.7, so the block is on the GitHub side for this private repo: usually Actions being restricted to certain actions (Settings → Actions → General → "Allow all actions"), or Actions minutes/billing on the account. Windows runners count double against private-repo minutes. The run page shows the exact reason.
- **No real model was used.** Ollama's model registry is blocked from this environment, so chat was verified against `tests/support/fake_ollama.py`, a protocol-faithful stand-in. The client uses Ollama's documented OpenAI-compatible streaming endpoint; your first real chat is the check.
- **Model shortlist unverified.** Tags and sizes in `services/models/.../loadouts.yaml` come from web search (Hugging Face and ollama.com were blocked). Each entry is marked `verified: false` and shown as such in the UI.
- **The `pre-universe` tag** exists locally but this environment's git proxy refused to push tags. The old landing page is still on `main` and in history. To publish the tag: `git tag -a pre-universe e39257b -m "Bolt landing page" && git push origin pre-universe`.
- **Safe-mode LKG** works for git checkouts (dev). Installed builds get their own release scheme in Phase 12.
- **Not in Phase 1 by design:** vault and search (Phase 2), the global Ctrl+Space command bar (Phase 2), tools, approvals, kill switch and budget caps (Phase 3), the full 3D universe (Phase 4), voice and vision (Phases 7–8). The HUD says so where relevant instead of showing dead controls.

## What's next: Phase 2 (Vault + Recall)

Storage layout and sidecars, ingestion pipeline and job queue, all core media types, hybrid search (FTS5 + LanceDB + reranker), the global-hotkey command bar, quick capture, watched folders, 2D grid/list views and automated restic backups. Done when you drop in 500 mixed files and find any of them by keyword or meaning in under a second.

Before Phase 2 it helps to have: the hardware report (`scripts\hardware-report.ps1`), your vault path, and a backup target (external drive or NAS).
