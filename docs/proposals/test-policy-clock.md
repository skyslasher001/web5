# Proposal: a protected policy test that fails right after a boot

Status: **waiting for your approval.** Nothing in it is applied yet.

Patch: [`test-policy-clock.patch`](test-policy-clock.patch). It changes one test in `tests/protected/test_policy.py`.

## The problem

`test_limits_are_checked_before_every_model_call` checks that a task that has run out of time is stopped. It
builds the late task with `started=0.0` and calls that "long ago". But `time.monotonic()` counts from when the
machine booted. If the machine has been up for less than the agent's 60 s timeout, a task started at 0 isn't late
yet. The policy engine then correctly says "allow", and the test fails with `assert 'allow' == 'deny'`.

It happened on 2026-10-22: the build container had been recreated a minute before the run. The app's own time
limit is correct. Only the test's idea of "long ago" was wrong. It could also fail on Windows just after a reboot.

## The fix

- The late task starts 61 s before now (`time.monotonic() - 61`), one second past the timeout, whenever the test
  runs. The assertion is unchanged: it must still be `deny`.
- The test also runs a second time with the clock pinned to 30 s after a boot, so the case that failed is now
  covered.

## What was run

2026-10-22, in a scratch worktree at the branch head:

- With the clock pinned to 30 s after boot, the old test fails (`assert 'allow' == 'deny'`).
- The new test passes on this machine's clock and 30 s after a boot. `tests/protected/test_policy.py` 11 of 11.
- ruff, ruff format and pyright are clean.

## To apply it

```sh
git apply docs/proposals/test-policy-clock.patch
uv run pytest tests/protected/test_policy.py
git add -A && git commit -m "Apply the test-policy-clock patch"
```
