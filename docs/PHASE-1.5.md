# Phase 1.5: fixes and hardening

Status: **delivered 2026-10-12, approved 2026-10-13.** The [protected-core patch](#protected-core-patch-applied-2026-10-13) was approved and applied. Phase 2 followed: see [PHASE-2.md](PHASE-2.md).

Phase 1.5 adds no features. It fixes every bug found in a review of Phase 1 and addresses the known issues that could be fixed from code. It also tests the model path against a real Ollama server for the first time. Each fix ships with a regression test.

## What was fixed

### Core (backend)

| Bug | What you'd have seen | Fix | Regression test |
| --- | --- | --- | --- |
| **REST handlers ran on worker threads** and touched loop-only state there: they published events to asyncio queues, cancelled tasks and used shared SQLite connections. | Events raised through REST (renderer error reports, *Stop* on a reply) could reach the HUD late or not at all. Rare cross-thread SQLite errors. | Every handler is `async def`, so all state is touched on the event loop. This also covers the WebSocket ticket store. | `test_core_threading.py` checks that every route is async (it walks nested routers, so it can't pass vacuously). It also checks that a REST-published event reaches a WebSocket client and that cancel works over REST. |
| **Core outlived a dead supervisor.** On Windows the venv's `python.exe` is a launcher, so killing it left the real Core running and holding port 47821. | After a supervisor crash or a hard kill: *address already in use* on the next start, and possibly safe mode for no real reason. | Core watches its parent process and shuts down by itself within about 0.25 s of it disappearing. | `test_core_orphan.py`: kill Core's parent, and Core stops serving and exits by itself. |
| **`GET /models` returned 500** when Ollama answered `/api/version` but then failed on `/api/tags`. | System panel error instead of *Ollama unreachable*. | Marked unreachable, with the real error. | `test_models_reports_ollama_unreachable_when_listing_fails` |
| **Assigning a chat model while Ollama was down returned 500.** | Generic failure toast. | Clear `503 Ollama is not reachable`. | `test_model_assignment_when_ollama_is_down_is_a_clear_503` |
| **One `/api/show` request per model on every model refresh.** | Needless load on Ollama, and a slower System panel with many models. | Capabilities come from `/api/tags` on Ollama ≥ 0.12. On older versions they're cached by model name and digest. The heuristic fallback is never cached. | `test_capabilities_are_looked_up_once_per_model_version`, `test_capabilities_listed_in_tags_need_no_show_calls` |
| **Defaulted fields were optional in the generated TypeScript types** (`capabilities`, `gpus`, …), so the UI hid real contract bugs behind `?? []`. | Nothing visible. The types lied. | API models subclass `universe_common.schema.ApiModel`, so a field the server always sends is required in `openapi.json` and `api.ts`. The `?? []` workarounds were removed. | Generated-types drift check, plus `pnpm -r typecheck` |
| **Core's first CPU reading in `/health` was always 0 %** (psutil needs a priming call). | Not shown in the HUD yet. A misleading number for anything that reads it. | Primed at startup. | — |

### Desktop and UI

| Bug | What you'd have seen | Fix | Regression test |
| --- | --- | --- | --- |
| **Navigation allowlist accepted any `file://` URL.** | A crafted link could navigate the main window to any local file. | Only `app://universe`, the safe-mode page itself, and the exact dev-server origin are allowed. Blocked attempts are logged. | `navigation.test.ts` |
| **The `app://` handler could be asked for a directory.** | Error responses for directory paths. | It serves regular files only. Anything else is 404. | `protocol.test.ts` ("serves regular files only") |
| **Error reports could be sent twice, or block forever.** Two flushes could run at once, and a report Core rejected as invalid (4xx) was retried forever, blocking every report behind it. | Duplicate entries in `errors`, or renderer errors silently never arriving. | The queue moved to `errorQueue.ts`: one flusher at a time, and invalid reports are dropped and logged (`error_report_rejected`). | `errorQueue.test.ts` |
| **The Electron main log grew without limit.** | A multi-GB `desktop.log` over months. | Rotates at 5 MB to `desktop.log.1`. | `logger.test.ts` |
| **Failed actions were silent.** Restart Core, Stop, open history, copy a command, *Try a normal start* and the palette actions all discarded their errors. | Clicking did nothing, with no feedback. | They go through `attempt()`, which posts *"<action> failed: <reason>"* to the activity ribbon. | `attempt.test.ts` |
| **Stuck pointer cursor** when a galaxy unmounted while hovered (for example, entering zen mode). | Hand cursor everywhere until the next hover. | Reset on unmount. | — |

### Windows and tooling

| Bug | Fix |
| --- | --- |
| **A CRLF checkout broke the drift checks** (`openapi.json`, design tokens) on Windows with `core.autocrlf=true`. | `.gitattributes` pins LF for text and marks binaries. `schema_export` writes LF explicitly. |
| **`pnpm gen:types` and the e2e fake-Ollama spawn used a shell.** That breaks on Windows paths with spaces and on `.cmd` shims. | No shell: the `openapi-typescript` CLI is resolved through Node's resolver and run with `process.execPath`. |

## Verified against a real Ollama

`tests/integration/test_real_ollama.py` starts a throwaway `ollama serve` (own port, own model store) and registers a tiny model that's generated on the fly: `tests/support/tiny_gguf.py` writes a 1-block llama GGUF in pure Python, so nothing is downloaded. It then checks the following against the real server:

- the model list and capabilities
- router selection
- token streaming through the OpenAI-compatible endpoint
- a clear error for an unknown model
- a full Core chat, from REST through the stored reply

It passed against **Ollama 0.40.0**. It runs whenever an `ollama` binary is on `PATH` (or `UNIVERSE_TEST_OLLAMA` points at one) and is skipped otherwise. The model talks gibberish, so this proves the protocol and the plumbing, not answer quality or speed.

## Protected-core patch (applied 2026-10-13)

Five more fixes touch the supervisor and CI, which AGENTS.md says only you can change, so they were proposed first. You approved them on 2026-10-13 and they're now applied. They're in [`proposals/phase-1.5-protected-core.patch`](proposals/phase-1.5-protected-core.patch), explained in [`proposals/phase-1.5-protected-core.md`](proposals/phase-1.5-protected-core.md):

1. Stopping or killing a service ends its **whole process tree**. Today on Windows only the venv launcher dies, which is the root cause behind the Core orphan fix above.
2. The supervisor joins its own **Job Object**, so services can't escape it in the moment between spawn and assignment.
3. A managed Ollama that **loses its port** to the Ollama tray app switches to using that instance instead of retrying forever.
4. `healthy_since` in supervisor status becomes a real timestamp.
5. CI moves to **Node 24 actions**. GitHub removed Node 20 from hosted runners on 2026-09-23.

All five come with regression tests. Before approval they were checked in a scratch worktree: the three cross-platform tests fail without the patch and pass with it, and the full suite passes. After applying, the suite passes in the repo too.

## Setup

Unchanged from [PHASE-1.md](PHASE-1.md#setup). After pulling, run `uv sync` and `pnpm install` again: `universe-common` now depends on pydantic directly.

## Demo script (≈3 minutes)

1. `pnpm dev`. Everything from the [Phase 1 demo](PHASE-1.md#demo-script-5-minutes) still works.
2. **Visible failures:** press `Ctrl+K` → **Simulate a Core crash**, and while it reconnects, open chat history (the clock icon). The activity ribbon says *Loading conversations failed: …* instead of nothing happening.
3. **Core follows its supervisor:** in Task Manager, end the supervisor's `python.exe` (the `-I -S` one). The old Core goes away: the Job Object takes it down, or its own parent watch does. Electron restarts the supervisor about 1 s later, and the new Core starts without *address already in use*.
4. **Real-Ollama test** (needs Ollama installed): `uv run pytest tests/integration/test_real_ollama.py -v`.

## Tests

| Suite | Count | New in 1.5 |
| --- | --- | --- |
| pytest (`uv run pytest`) | 105 (100 + 5 real-Ollama tests that skip without an `ollama` binary) | threading invariants (3), orphan exit, `/models` when listing fails, 503 on assignment, capability caching (2), real Ollama (5) |
| Vitest (`pnpm exec vitest run`) | 35 | navigation allowlist, log rotation, error-report queue (4), regular-files-only `app://`, `attempt()` |
| Playwright Electron (`pnpm test:e2e`) | 6 | unchanged, re-run green |
| From the protected-core patch (applied 2026-10-13) | pytest +3 (108 in total), +1 Windows-only | tree kill, Ollama adoption, wall-clock status, Job Object (Windows) |

Everything passed locally (Linux, Python 3.12.13, Node 22): `ruff`, `ruff format`, `pyright`, `eslint`, `prettier`, `tsc`, the generated-file checks, `pnpm build` and the e2e run.

## Known limitations (still open)

- **Not yet run on Windows, because CI still can't start.** The first run of `.github/workflows/ci.yml` ended in `startup_failure` before any job ran. That's a repository or account setting, not the workflow: it passes `actionlint`. Check Settings → Actions → General → "Allow all actions and reusable workflows", and Actions minutes or billing for this private repo (Windows minutes count double). The failed run's page names the exact reason. The Phase 1.5 fixes remove the Windows problems found by review (CRLF, shells, launcher orphans), but Windows CI is the real test.
- **No real LLM yet.** The real-Ollama test uses a generated toy model. Ollama's registry (ollama.com) and Hugging Face are still unreachable from the build environment, so first-token latency and answer quality are measured on your PC.
- **Model shortlist still unverified.** For the same reason, `loadouts.yaml` stays `verified: false`.
- **The `pre-universe` tag still isn't on GitHub.** The environment's git proxy refuses tag pushes (retried in 1.5). Run `git tag -a pre-universe e39257b -m "Bolt landing page" && git push origin pre-universe`. The old page is in `main`'s history either way.
- **Not in scope by design:** everything from Phase 2 on.

## What's next: Phase 2 (Vault + Recall)

Approved 2026-10-13. See [PHASE-1.md → What's next](PHASE-1.md#whats-next-phase-2-vault--recall). Still useful from you: fix the Actions setting so Windows CI runs, and send the hardware report, your vault path and a backup target.
