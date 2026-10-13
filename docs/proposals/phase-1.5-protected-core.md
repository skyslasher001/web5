# Proposal: Phase 1.5 fixes to protected core

Status: **approved by the owner and applied on 2026-10-13.** Kept as the record of what changed and why.

These fixes touch paths in [`protected-core.txt`](../../protected-core.txt) (the supervisor and CI), so per AGENTS.md they were proposed rather than applied. The diff is [`phase-1.5-protected-core.patch`](phase-1.5-protected-core.patch).

## Apply

```powershell
git apply docs/proposals/phase-1.5-protected-core.patch
uv run pytest tests/integration/test_supervisor.py
git add -A
git commit -m "Supervisor: kill whole process trees, adopt an external Ollama, wall-clock healthy_since; CI: Node 24 actions"
```

To decline it, do nothing. The app works without it. The Core-side orphan watch added in Phase 1.5 covers the worst case of bug 1 (see below).

## What it changes

| # | Bug | Fix | Files |
| --- | --- | --- | --- |
| 1 | **Stopping or killing Core on Windows orphans the real Core process.** A venv's `python.exe` is a launcher that runs the real interpreter as a child. `Popen.terminate()`/`kill()` end only the launcher. The orphan then holds port 47821, so the restarted Core can fail to bind. Two failed boots enter safe mode. | `kill_tree()`: `taskkill /PID … /T /F` on Windows. On POSIX each service already leads its own session, so it signals the process group: SIGTERM to stop gracefully, SIGKILL on timeout. Used by `stop()` (restart, exit safe mode, shutdown, boot timeout) and by `kill()` (simulate crash). | `service.py`, `supervisor.py` |
| 2 | **Services can escape the Job Object.** Each child was added to the kill-on-close job only after `Popen` returned. A launcher's child created in that gap is not in the job, so it survives a supervisor crash. | The supervisor joins its own job at startup, so every child is a member from the moment it's created. The per-child assignment stays as a fallback. | `winjob.py` |
| 3 | **A managed Ollama that loses its port loops forever.** If you start the Ollama tray app while UNIVERSE is starting, our `ollama serve` fails ("address in use") and is retried with backoff indefinitely. Meanwhile the System panel shows an error, although Ollama is reachable. | When our Ollama exits but the Ollama URL still answers, the supervisor switches to `external` and uses that instance. The existing 5 s recheck takes over again if the external instance goes away. | `supervisor.py` |
| 4 | **`healthy_since` in supervisor status was a monotonic clock value** (seconds since boot) while `supervisor.started_at` next to it is epoch seconds. Nothing displays it yet, but anything that does would show nonsense. | Status reports epoch seconds. The state machine keeps using the monotonic value. | `service.py`, `supervisor.py` |
| 5 | **CI uses Node 20 actions.** GitHub removed Node 20 from hosted runners on 2026-09-23. `astral-sh/setup-uv@v6` and `actions/upload-artifact@v4` are Node 20 actions. | `setup-uv@v10` and `upload-artifact@v7`, both Node 24. The only breaking change in setup-uv v10 turns off caching for `pull_request_target`/`workflow_run`/`release` events, none of which this workflow uses. | `.github/workflows/ci.yml` |

**Regression tests** (in the patch, because they fail without it):

- `test_kill_and_restart_take_the_whole_process_tree`: Core behind a launcher stand-in (`tests/support/launcher.py`), then `kill` and `restart`. Each must end the real process and come back healthy.
- `test_managed_ollama_adopts_an_instance_that_takes_its_port`
- `test_status_reports_healthy_since_as_wall_clock_time`
- `test_children_belong_to_the_job_from_creation`: Windows only, in a fresh interpreter. It checks `IsProcessInJob` for a child spawned without explicit assignment.

## Verified

- The patch applies cleanly (`git apply --check`) on top of the Phase 1.5 commit.
- Without the source changes, the three cross-platform tests fail. The tree-kill test also leaves orphaned processes behind, which is the bug itself.
- With the patch, in a scratch worktree, the full pytest suite gives 107 passed and 1 skipped (the Windows-only test). The new tests passed 5 runs in a row, and no processes were left over.
- `ruff`, `ruff format`, and `pyright` pass, with pyright run for both the Linux and Windows platforms. `actionlint` 1.7.7 passes on the workflow.

**Not verified:** the Windows paths (`taskkill`, the Job Object self-assignment and its test) haven't run on Windows. This environment is Linux, and CI hasn't started yet (see PHASE-1.5.md). They're small and use documented APIs, but the first Windows CI run is their real test.

## Risk

- **Supervisor in its own job:** when the supervisor exits, all its services exit with it. That was already the intent. If Electron itself runs inside a job that forbids nesting, the self-assignment fails silently and behaviour falls back to today's.
- **`taskkill /F`:** Core has no graceful shutdown path on Windows today, since `terminate()` was already `TerminateProcess`. So this isn't a regression in grace, only in scope (the whole tree).
- No change to cost, privacy, or the security model.
