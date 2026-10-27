# Proposal: protected-core fixes from the 2026-10-22 full sweep

Status: **waiting for your approval.** Nothing in it is applied yet.

Patch: [`sweep-fixes-protected.patch`](sweep-fixes-protected.patch), on top of the branch after the sweep's other
fixes (`745bfe2`; the review-fixes patch is applied). It is separate from [`test-policy-clock.patch`](test-policy-clock.patch) and doesn't
touch the same file, so the two apply in either order.

## Why this needs you

A sweep of the protected code (Sentinel, Forge's guards and checks, the supervisor's releases and safe mode,
and the kill switch in Electron main) found ten problems. All ten reproduced. The fixes are in protected files,
so they come to you as a patch. One file in it isn't protected: `apps/desktop/src/main/index.ts`. It needs two
lines to connect the new kill-switch code, and it's in the same patch so the fix arrives whole.

**Until it's applied, read a Forge proposal's file list yourself before you approve it.** The first bug lets a
file with a non-ASCII name (`ü`) get past Sentinel, Core's protected check and the supervisor's own check.

## What it fixes

| # | Where | Problem | Fix |
| --- | --- | --- | --- |
| 1 | `sentinel.py`, `forge.py`, `releases.py` | git **quotes non-ASCII file names** (`"services/supervisor/\303\274.py"`). Sentinel lost the file at the `" b/"` header split, so it reviewed none of its lines. Core's file list and the supervisor's path check got the quoted name, which matches no glob. A protected file named with a `ü` could be **applied**. The supervisor's check was also case-sensitive, while Windows treats `Services/Supervisor/run.py` as the protected file itself. | Core and the supervisor run git with `-c core.quotePath=false`, so both hashes still agree. They read names with `-z`. Sentinel reads the header as the same name twice, so a name containing `" b/"` is also read whole. A name git quotes anyway (`"`, `\`, control characters) is blocked by Sentinel (`unreviewable`), refused by `Worktree.resolve`, and refused by the supervisor. Sentinel and the supervisor casefold paths, like Core. Sentinel's `test-config` rule ignores case. |
| 2 | `sentinel.py` `NETWORK`, `tests/protected/test_invariants.py` | These forms weren't seen: `from urllib import request`, `from http import client`, `from asyncio import open_connection`, `importlib.import_module(…)`, `__import__(…)`. Any path containing `tests/`, or named `test_*.py`, was exempt from the network rule, even inside a package that ships. The invariant test also skipped every `/tests/` folder. | Sentinel matches these forms and blocks any dynamic import (you can still apply one by hand). Only the top-level `tests/` folder is exempt, for the network and subprocess rules. The invariant test also reads `from X import Y` as module `X.Y`, sees `import_module("…")` and `__import__("…")` with a literal name, bans `asyncio.open_connection`, and exempts no folder. |
| 3 | `sentinel.py` | An added line starting with `++` is `+++…` in the diff, and a removed line starting with `--` is `---…`. Both were **skipped as file headers**, so `++__import__('httpx').get(…)` went unseen. | `---` and `+++` count as headers only between `diff --git` and the first `@@`. |
| 4 | `sentinel.py` | Only assertion **counts** were compared. `assert x == 42` → `assert x == 42 or True`, or an added early `return` in a test, passed. | New block rules. `assertion-changed`: an existing assertion line removed and not re-added with the same text. Re-indenting or moving it is fine. `test-short-circuited`: an added `return` or `pass` inside a test function that was already there. A brand-new test is never flagged, and neither is a helper defined inside a test. |
| 5 | `releases.py` `rollback`, `supervisor.py` | On a dirty checkout, the refusal came before the conflict handling. The release stayed `watching`, and the watch **retried every 0.2 s tick for ever**, logging each time. | An automatic rollback (`automatic=True`, from the watch) that is refused marks the release `rollback_failed` with the reason, and the watch stops. A rollback you ask for is refused as before and leaves the status alone, so you commit or stash and try again. Your files are never touched. |
| 6 | `releases.py` `apply` | The tag number was `len(releases)+1`. If `releases.json` was lost or corrupt, `git tag` collided **after** the fast-forward merge, so the change was applied but not recorded or watched. | The next number is one past every number in use, in `releases.json` and in the `universe/release-*` / `pre-release-*` tags. The tags are made before the merge. A failed merge deletes only the tags this apply made, so the release can be retried. |
| 7 | `lkg.py` | Safe mode's `PYTHONPATH` held only core, common, agents and models. **Vault, research and voice were imported from the broken current checkout** (its editable installs). | Every service package: the known seven, plus any other `services/*/src` in the LKG worktree, except the supervisor. |
| 8 | `forge_verify.py`, `forge_tools.py` | The kill switch cancelled Forge's task, but the verification ran on in its thread. `subprocess.run` ran to its 15-minute timeout, with the test run's child processes too. | `run()` uses `Popen` and polls a `stop` callable every 0.25 s. On stop (or the timeout) it kills the whole process tree (its own session on POSIX, `taskkill /T` on Windows). `Verifier(stop=…)` checks it before every step. A stopped repro never counts as "fails on base". `forge.check` passes the kill switch's state. |
| 9 | `protected/killswitch.ts` | Electron marked itself engaged, then the supervisor call threw (the supervisor was restarting). The state file was never written, so **the restarted supervisor booted Core with the kill switch off**. The IPC call also rejected. | The failure is caught: Electron stays engaged and remembers the engage as unsent. `resync()` sends it again when the supervisor reports `ready`. A failed release stays engaged. |
| 10 | `protected/killswitch.ts`, `index.ts` | Core's `POST /api/v1/killswitch` wrote the state file, but Electron read that file only at launch. **The mic wasn't revoked**, and `consent.request(true)` still worked. | Electron main checks the state file every second (`watchKillSwitchFile`). An engage written by Core stops capture and marks Electron engaged (`observe`). Only an engage is followed: releasing still needs the native dialog. A read that fails mid-replace doesn't engage by itself. At launch, an unreadable file still counts as engaged. |

## Tests

New regression tests. Each one fails on the protected code as it is now and passes with the patch. The failure
each one showed before is listed with it.

- `tests/protected/test_sentinel.py`
  - `test_file_names_git_quotes_or_changes_case_cant_slip_past` (1): `assert 'pass' == 'block'` (the quoted
    conftest with `import httpx`).
  - `test_every_way_of_importing_a_network_client_is_blocked` (2): `AssertionError: from urllib import request`.
  - `test_added_lines_that_look_like_file_headers_are_still_reviewed` (3): `assert 'pass' == 'block'`.
  - `test_a_changed_assertion_or_an_early_return_in_a_test_is_blocked` (4): `assert 'pass' == 'block'`.
- `tests/protected/test_invariants.py`
  - `test_the_egress_invariant_sees_every_import_form` (2). The scan is now a helper, `_egress_violations`, and
    the existing test asserts it finds nothing in `services/`. Run on the five import forms, the old `_imports`
    saw `urllib`, `http`, `asyncio`, `importlib` and nothing at all, so it missed all five. It also skipped every
    `/tests/` folder.
- `tests/protected/test_releases.py`
  - `test_names_git_quotes_or_spells_in_another_case_are_still_protected` (1): `Regex pattern did not match`.
    The apply wasn't refused as protected core. Run against the old supervisor, a branch adding
    `services/supervisor/ü.py`, hashed the way Core hashed it then, was **applied** as `universe/release-1`.
  - `test_a_lost_releases_file_doesnt_reuse_a_tag` (6): `ReleaseError: git tag universe/pre-release-1 failed:
    fatal: tag 'universe/pre-release-1' already exists`. That error came after the merge had already happened.
  - `test_an_automatic_rollback_on_a_dirty_checkout_stops_the_watch` (5): `TypeError: rollback() got an
    unexpected keyword argument 'automatic'`.
  - `test_the_watch_stops_when_it_cant_roll_back` (5, slow, the real supervisor loop): `timed out`. The release
    never left `watching`. With the patch, the rollback is refused exactly once and the watch stops.
  - `test_safe_mode_runs_every_service_package_from_the_lkg_copy` (7): `AssertionError: vault`.
  - `test_a_failed_merge_leaves_no_tags_behind` (6) guards the new tag-before-merge order. It passed before too,
    because the old code tagged after the merge.
  - The `sh` helper now runs git with `core.quotePath=false`, as the supervisor and Core do. The approved hash
    it computes then matches theirs for non-ASCII names.
- `tests/unit/test_forge_core.py`
  - `test_names_git_would_quote_are_reviewed_as_real_paths` (1): `assert ['"services/s...conftest.py"'] ==
    ['services/su.../conftest.py']`.
  - `test_a_running_check_stops_when_asked` (8): `TypeError: run() got an unexpected keyword argument 'stop'`.
    With the patch, the check and its grandchild process are gone about a second after `stop`.
- `apps/desktop/src/main/protected/killswitch.test.ts`
  - "sends an engage again when the supervisor comes back" (9): `Error: The supervisor is not running`.
  - "follows an engage written by Core and stops capture" (10): `TypeError: ks.observe is not a function`.
  - "watches the state file" (10): `TypeError: peekKillSwitchFile is not a function`.

The `index.ts` wiring (`supervisor.on('ready', …)` and the file watch) is two lines of Electron startup and has no
unit test of its own. The kill-switch e2e test runs through it.

## To apply it

```sh
git apply docs/proposals/sweep-fixes-protected.patch
uv run pytest tests/protected tests/unit/test_forge_core.py tests/integration/test_supervisor.py
pnpm exec vitest run apps/desktop
git add -A && git commit -m "Apply the sweep-fixes protected-core patch"
```

## What to look at closely

- `_diff_path`, `_parse` and `_changed_assertions` in `sentinel.py`: the header state machine, the
  enclosing-function tracking for early exits, and what counts as a changed assertion.
- `NETWORK` in `sentinel.py`: a Forge change with any `import_module` or `__import__` is now blocked. Apply such
  a change by hand if you want it.
- `Releases.apply`: tags first, then the merge, and on failure it deletes only the tags it made.
- `forge_verify.run`: the poll loop and `_kill_tree`.
- `KillSwitchControl.set`, `resync` and `observe` in `killswitch.ts`.

## Known limits

- Sentinel reads one line at a time. A parenthesised import across lines (`from urllib import (\n request)`)
  isn't caught there. The invariant test parses the AST and does catch it, but only in code already on the branch.
- Early-exit tracking follows indentation and the function name in git's `@@` line. A test whose signature spans
  several lines, or a method inside a test class, may not be recognised. That can miss a weakened test but never
  blocks a good one.
- Core's file list still names only the new path of a rename. The supervisor's `--no-renames` check covers that
  case, and Sentinel blocks renaming a test.
- With `quotePath=false`, a proposal made **before** the patch whose diff has a non-ASCII file name now gets
  "its hash differs". Ask Forge to redo it.
- Electron checks the state file once a second, so after Core engages the kill switch the mic can stay on for up
  to a second. Core has already stopped voice by then (`_stop_voice_on_kill`).

## What was run

2026-10-23, in a scratch worktree at the branch head `745bfe2` (after the sweep's other fixes were merged) with
this patch applied:

- **Python:** the full suite 420 passed, 8 skipped. That is the branch's 407 plus the 13 new tests; the skips are
  7 real-voice-model tests and 1 Windows-only test. ruff, ruff format and pyright clean.
- **Vitest:** 221 of 221, including the desktop suite's 3 new kill-switch tests. eslint (`--max-warnings=0`),
  prettier and `pnpm -r typecheck` clean.
- **Electron e2e** (`pnpm build`, then `app.spec.ts` + `safe-mode.spec.ts` under xvfb): 16 of 16, including the
  full Phase 5 loop (Forge's diff, Sentinel, the approved hash, apply and roll back), the Phase 7 consent test and
  the kill-switch test.
- **Each new test fails without the fixes:** run against the protected code as it is now, 11 Python tests and 3
  Vitest tests failed with the errors listed above; the invariant test's old logic was checked separately.
- First built at `0b33a69`; rebased with `git apply --3way` onto `745bfe2` (one overlap in `index.ts`, with the
  tray fix, merged cleanly). `git apply --check` on `745bfe2`: OK. The patch holds the 14 code and test files only.
