# Proposal: protected-core fixes from the Phase 5–7 review

Status: **applied 2026-10-22** (owner-approved, DECISIONS row 22). It applied cleanly onto `0d7ac49`.

Patch: [`review-fixes-protected.patch`](review-fixes-protected.patch), on top of the Phase 5 and Phase 7 patches
(applied 2026-10-21, df2af16). Review notes: [`docs/handoff/DECISIONS.md`](../handoff/DECISIONS.md) row 21.

## Why this needs you

You asked for the Phase 5 and Phase 7 patches to be applied and for Phases 5, 6 and 7 to be reviewed. The review
found 24 problems. Everything outside protected core is fixed on the branch, each with a regression test. The
fixes below are in files that became protected when the Phase 5 patch was applied (Forge, Sentinel, the
supervisor's releases, microphone consent). You approved two specific patches, not later edits to those files,
so these come to you as a third patch.

**Until it's applied, don't approve a Forge proposal.** The first bug below means applying any Forge change
replaces your `.venv` with a broken link.

## What it fixes

| # | Where | Problem | Fix |
| --- | --- | --- | --- |
| 1 | `forge.py` `Worktree.commit` | Verification links the repo's `.venv` and `node_modules` into the worktree. `.venv/` in `.gitignore` matches only directories, not a link with that name, so `git add -A` **committed the links**. Applying the proposal replaced your real `.venv` with a dangling link. | The verification links are excluded from `git add`. Any other symbolic link is refused (`Forge doesn't commit symbolic links`). The commit runs only when something is staged, because the links stay untracked. |
| 2 | `protected/sentinel.py` | A patch could change **how the checks run**: a root `conftest.py` hook, `addopts = "-k repro"` in `pyproject.toml`, or a vitest/eslint config. That could make a failing suite "pass" while Sentinel saw nothing wrong. | New block rule `test-config`: conftest.py, pytest.ini, tox.ini, setup.cfg, pyright/ruff config, vitest/vite/playwright/eslint/prettier config, and `[tool.pytest/pyright/ruff/coverage]`, `addopts`, `testpaths` or `python_files` lines in `pyproject.toml`. |
| 3 | `sentinel.py`, `forge.py` `Worktree.diff`, `releases.py` | One NUL byte makes git treat a file as binary. The diff then shows only "Binary files differ", which **hides the code** from Sentinel and from you. It also makes the approved hash cover nothing. | Diffs use `--text`, in both Core and the supervisor, so the hashes still agree. New block rule `unreviewable`: a binary change, a NUL byte, or a symbolic link. |
| 4 | `releases.py` `apply` | The supervisor's own checks didn't refuse symbolic links. | Refused (`It adds or changes a symbolic link`), independently of Forge and Sentinel. |
| 5 | `releases.py` `rollback` | If you'd edited the same lines after a release, the revert **conflicted**. The checkout was left mid-revert, and the watch **retried every tick**. | `git revert --abort` puts the checkout back as it was. The release is marked `rollback_failed` with the reason, so the watch stops. The System panel shows it in red and says to revert it by hand. That UI part is on the branch. |
| 6 | `supervisor.py`, `service.py` | The watch counted **every restart** as a crash. Restarting Core twice from the System panel, or changing models, during the 30-minute watch **rolled back a good release**. | A new `crashes` counter counts only crashes and failed boots. The watch compares against that. |
| 7 | `supervisor.py` `apply_release` | Applying while in safe mode was allowed. The watch then read safe mode as the release failing, and **rolled it back at once**. | Refused in safe mode (`get Core healthy before applying changes`). |
| 8 | `forge.py`, `forge_verify.py`, `releases.py` | Git and check output was decoded strictly, and on Windows with the ANSI code page (`-I` ignores `PYTHONUTF8`). **One non-UTF-8 byte crashed** an apply or a verification. | Everything is decoded as UTF-8 with replacement, the same in Core and the supervisor. |
| 9 | `protected/consent.ts` | The native dialog's "yes" lasted the whole launch. After the kill switch, or a reload or crash of the page, the mic could be **turned on again without asking**. | The kill switch and a lost window reset it. The next "on" shows the dialog again. |
| 10 | `index.ts` tray | "Microphone on: turn it off" only flipped consent. Chromium keeps an open stream running after a permission is revoked, so **the mic stayed live** if the page didn't stop it. | It revokes and reloads the window when the mic was on, the same as the kill switch. |
| 11 | `protected/supervisor.ts` | The release status type didn't include `rollback_failed`. | Added. The bridge type on the branch already has it. |

## Tests

New regression tests. Each one fails on the protected code as it is now and passes with the patch:

- `tests/unit/test_forge_core.py::test_verification_links_never_enter_a_proposal` (1)
- `tests/protected/test_sentinel.py`: `test_changing_how_the_checks_run_is_blocked`,
  `test_content_hidden_from_the_review_is_blocked` (2, 3)
- `tests/protected/test_releases.py`: `test_a_symbolic_link_is_refused`,
  `test_the_approved_hash_covers_binary_content`, `test_a_rollback_that_conflicts_changes_nothing_and_isnt_retried`,
  `test_restarts_you_ask_for_dont_roll_a_release_back`, `test_nothing_is_applied_in_safe_mode`,
  `test_a_change_that_isnt_utf8_is_still_read` (3–8). The helper `forge_branch` now hashes the `--text` diff,
  as the supervisor does.
- `apps/desktop/src/main/protected/consent.test.ts`: "asks again after the kill switch or a new page" (9)

The tray click (10) is Electron menu wiring and has no unit test. The e2e can't click the OS tray, and Playwright
can't drive native menus. It calls the same `revoke` + reload path that the kill-switch e2e test already covers.

## To apply it

```sh
git apply docs/proposals/review-fixes-protected.patch
uv run pytest tests/protected tests/unit/test_forge_core.py
pnpm exec vitest run apps/desktop
git add -A && git commit -m "Apply the review-fixes protected-core patch"
```

## What to look at closely

- `Worktree.commit` in `forge.py`: the pathspec excludes and the symlink refusal.
- `TEST_CONFIG`, `PYPROJECT_TOOLS` and `_hidden` in `sentinel.py`: what is now blocked.
- `Releases.rollback`: the abort, and the `rollback_failed` record.
- `crashes` against `restarts` in `supervisor.py`.

## What was run

2026-10-21, in a fresh scratch worktree at the branch head (`470ba3d`) with this patch applied:

- **Python:** the full suite 368 passed, 8 skipped. That is the branch's 359 plus the 9 new tests; the skips are 7
  real-voice-model tests and 1 Windows-only test. ruff, ruff format and pyright clean.
- **Vitest:** 188 of 188, including the desktop suite's 52 (one new). eslint, prettier and the type check clean.
- **Electron e2e** (`app.spec.ts` + `safe-mode.spec.ts`): 16 of 16, including the full Phase 5 loop (inject a bug,
  Forge fixes it, approve, apply, roll back) and the Phase 7 consent and kill-switch tests.
- **Each new test fails without the patch:** run against the protected code as it is now, all 9 new Python tests
  fail (the links, Sentinel, release, supervisor and encoding tests). So does the consent test.
