# Proposal: the supervisor's git calls hang on Windows

Status: **waiting for your approval.** Nothing in it is applied yet.

Patch: [`supervisor-stdin.patch`](supervisor-stdin.patch). It changes two lines' worth of protected supervisor
code (`releases.py`, `lkg.py`) and adds one unit test. It applies cleanly before or after
[`sweep-fixes-protected.patch`](sweep-fixes-protected.patch).

## The problem

On Windows, **approving a Forge change never applies it**, and the System panel's Releases list never loads.
CI's Windows e2e showed it: the Phase 5 test waited 60 s for the fix to land, the supervisor logged neither
`release_applied` nor `release_refused`, and Electron logged `forge_sync_failed: TimeoutError` at every start
(its `GET /releases` gets 5 s). `POST /killswitch` on the same server answered at once.

The cause: Electron starts the supervisor with stdin as a pipe and keeps it open; the supervisor's stdin-watch
thread blocks reading it (end of file means Electron is gone). The supervisor's git calls (`Releases._git`,
`lkg._git`) don't set `stdin`, so each git child **inherits that pipe**. On Windows a child's C runtime
queries its standard handles at startup, and a query on a pipe that another thread is reading synchronously
waits until that read finishes: here, until Electron quits. So every git call hung: listing releases, applying,
rolling back, and last-known-good. On Linux and macOS nothing waits, which is why every other run passed.

The services the supervisor starts (`service.py`) already pass `stdin=subprocess.DEVNULL`. Only the two git
helpers didn't.

## The fix

- `Releases._git` and `lkg._git` pass `stdin=subprocess.DEVNULL`.
- New `tests/unit/test_supervisor_stdin.py`: every `subprocess` call anywhere in the supervisor must set
  `stdin`. It reads the source, so it holds on every platform and for calls added later.

## Tests

- `tests/integration/test_supervisor_e2e.py::test_releases_answer_while_electron_holds_stdin_open` (on the
  branch) runs the real supervisor the way Electron does (`python -I -S`, stdin a pipe held open) on a scratch
  repository, then times `GET /releases` and an apply. **On CI's Windows runner it fails on the current code**
  (`GET /releases` timed out after 10 s while `/status` answered). It passes on Linux either way.
- `test_the_supervisor_stdin_proposal_fixes_it` (on the branch, temporary) runs the same check on a copy of the
  supervisor with this patch applied, so CI's Windows runner shows the fix works before you apply it. Delete
  it when you apply the patch: the patch no longer applies once it is in.
- `tests/unit/test_supervisor_stdin.py` (in the patch) fails on the current code, naming `lkg.py:15` and
  `releases.py:78`, and passes with the patch.

## What was run

2026-10-27, in a scratch worktree at `78b5e73` with the patch applied:

- `tests/protected`, `tests/unit/test_supervisor_stdin.py`, `tests/integration/test_supervisor.py` and
  `tests/integration/test_supervisor_e2e.py`: 67 passed, 1 skipped (the Windows-only Job Object test).
- The same with `sweep-fixes-protected.patch` applied first: 78 passed, 1 skipped.
- ruff, ruff format and pyright are clean.

## To apply it

```sh
git apply docs/proposals/supervisor-stdin.patch
uv run pytest tests/unit/test_supervisor_stdin.py tests/protected tests/integration/test_supervisor_e2e.py
git add -A && git commit -m "Apply the supervisor-stdin patch"
```

Then delete `test_the_supervisor_stdin_proposal_fixes_it` from `tests/integration/test_supervisor_e2e.py`.
