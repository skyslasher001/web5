# Proposal: Phase 5 protected core — Sentinel, Forge's definition, releases and the approval dialog

Status: **applied 2026-10-21** (owner-approved, DECISIONS row 21) in `df2af16`. Both patches were applied with
`git apply --3way` onto the branch head. They overlap in `apps/desktop/src/main/index.ts`, where each adds a
block before `const killSwitch`, and both blocks were kept. Review fixes to the same files are a separate
proposal: [review-fixes-protected](review-fixes-protected.md).

Patch: [`phase-5-protected-core.patch`](phase-5-protected-core.patch). Design: [ADR-0014](../adr/0014-phase-5-forge-sentinel.md).

## Why this needs you

Forge itself is built and committed: issues and triage, worktrees, verification, proposals, the Forge panel,
approval cards and the System panel's releases. Everything that **decides** whether a change is safe, or
**applies** it, is protected core (AGENTS.md, `protected-core.txt`), so it arrives as this patch:

- Sentinel's review;
- Forge's own definition and limits;
- the supervisor's apply, watch and rollback;
- the native approval dialog in Electron main.

Until it's applied:
- **No Forge agent:** its YAML is protected.
- **No Sentinel review**, so no proposal can be approved.
- **No apply or rollback.**

The Forge panel says so, the Fix buttons are disabled, and the done-when e2e test stops at that point.

## What it adds

| Where | What |
| --- | --- |
| `agents/forge.yaml`, `agents/prompts/forge.md` | **The Forge agent.** Large local model, write tier. Its only tools: read issues, search and read the code, open a worktree, write in it, run the checks, propose. Its prompt says: test first, smallest fix, never weaken a test, never touch protected core or the vault. Up to 40 steps. |
| `agents/sentinel.yaml`, `agents/prompts/sentinel.md` | **The Sentinel agent**, read-only, for a short written review. Its verdict comes from the deterministic code below. |
| `services/core/.../protected/sentinel.py` | **Sentinel's deterministic review** of every diff. It blocks when a change touches protected core, deletes, renames or skips a test, removes tests or assertions, adds network code outside the egress gate, raises an agent's permission tier, or contains text aimed at the reviewers. It flags high risk for dependency or lockfile changes, migrations, new subprocess or dynamic code, consent and capture code, and agent tool lists. Over 200 changed lines is medium risk. Standard library only, no model. |
| `services/supervisor` (`releases.py`, `supervisor.py`, `control.py`, `config.py`) | **Releases.** `GET /releases`, `POST /releases/apply`, `POST /releases/rollback` on the control port, which only Electron main can reach. Before applying, the supervisor redoes every check itself: your checkout must have no uncommitted changes; the branch tip must be the verified commit; the code must not have moved since Forge started; the diff's hash must match the one you were shown; no changed path may be protected, judged by the supervisor's **own copy** of `protected-core.txt` read at startup (and the checkout's manifest must still match it). Then it tags, fast-forwards, restarts Core and **watches for 30 minutes**: two crashes or safe mode roll it back on their own. Rollback adds revert commits, so anything you committed since stays. Standard library only, as before. |
| `apps/desktop/src/main/protected/forge.ts` (+ `supervisor.ts`, and `index.ts` wiring) | **The approval dialog.** Approve on a card → main fetches the proposal and refuses anything not ready: verification failed, Sentinel missing or blocking, protected core touched, or no verified commit. Otherwise a **native dialog** shows the title, why it broke, the risk, the files, Sentinel's notes and the change's hash. Only "Apply" there calls the supervisor. Rollback asks the same way. The supervisor restarts Core after each apply and rollback (and may roll back on its own), so main re-syncs Core's record with the supervisor's releases each time Core comes back healthy. |
| `protected-core.txt` | Adds Forge's prompts and its own code: `forge.py` (worktree guards, the daily cap), `forge_tools.py` and `forge_verify.py` (the checks it's judged by). Forge can't propose changes to how it's checked. |
| `tests/protected/test_sentinel.py`, `test_releases.py`, `apps/desktop/.../protected/forge.test.ts` | 10 Sentinel tests, 10 release tests (including a release that makes Core crash and rolls itself back, and a protected file renamed to an unprotected path being refused), and 8 approval-dialog tests (including Core catching up after it was restarting when the release was recorded). |

## How it was tested

In a scratch worktree at the branch head with this patch applied:
- the full Python suite;
- the desktop type check, eslint and its Vitest suite;
- the done-when e2e: an injected bug in a scratch repository, reported in the Forge panel, fixed by Forge with a test that fails first, reviewed by Critic and Sentinel, approved through the native dialog, applied by the supervisor, then rolled back from the System panel.

Results (2026-10-14): the patched e2e suite (`app.spec.ts` + `safe-mode.spec.ts`) passed 15 of 15, the done-when included; the desktop Vitest suite passed 36 of 36; the full Python suite passed 256 with 1 Windows-only skip (the real-Ollama tests included).

A readiness audit (2026-10-18) then found and fixed a set of issues in this patch before you apply it: Sentinel's network block list was widened to match the project's own egress invariant (it was missing `http.client`) and to flag an agent narrowing its `requires_approval`; the supervisor's protected-path gate now uses `--no-renames` so renaming a protected file to an unprotected path can't slip past it, and it tags the pre-release only after the fast-forward merge succeeds; the `services/sentinel/**` manifest glob (which matched nothing) was replaced with a comment pointing at the real `protected/sentinel.py`; and the Electron supervisor client's release return types were corrected. Each ships a regression test (now 10 Sentinel + 10 release tests). The matching fixes to the non-protected Forge code are already on the branch.

## To apply it

```sh
git apply docs/proposals/phase-5-protected-core.patch
uv run pytest tests/protected tests/integration/test_forge.py
pnpm exec vitest run apps/desktop
git add -A && git commit -m "Apply the Phase 5 protected-core patch"
```

## What to look at closely

- `notApprovable` and the dialog text in `forge.ts`: what you'll be shown before anything applies.
- `Releases.apply` in `releases.py`: the checks the supervisor redoes, and that it refuses a dirty checkout.
- Sentinel's block rules in `sentinel.py`: they decide what can never reach you.
- **Flag (security):** verification runs Forge's code as a normal process with a scrubbed environment (no
  tokens, offline, dead proxy). That limits accidents, not a determined attacker; containers would (ADR-0014).
