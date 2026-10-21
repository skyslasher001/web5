# Phase 5: Forge + Sentinel v1

Status: **delivered 2026-10-14, reviewed 2026-10-21, waiting for your approval.** The protected-core patch is
applied ([proposal](proposals/phase-5-protected-core.md), `df2af16`). The review's protected-core fixes are a new
proposal, [review-fixes-protected](proposals/review-fixes-protected.md). **Apply it before you approve a Forge
change**: without it, applying one replaces your `.venv` with a dangling link.

Forge keeps UNIVERSE healthy. It notices what's broken (errors, failing background jobs, your bug reports),
reproduces it with a failing test, fixes it in its own git worktree, proves the fix and asks you. Nothing
reaches your code until you press Apply in a native dialog. The supervisor then applies it, watches it for 30
minutes, and rolls it back on its own if Core starts crashing. You can roll it back yourself with one click.
Design decisions are in [ADR-0014](adr/0014-phase-5-forge-sentinel.md).

**Done when** (SPEC §25): *"I inject a deliberate bug, Forge finds it and proposes a tested fix, I approve, it
applies, and one-click rollback works."* `tests/e2e/app.spec.ts` › *done when (Phase 5)* drives the real app on
a scratch repository whose `add()` subtracts:

1. You report "add(2, 3) returns -1 instead of 5" in the Forge panel. It becomes an issue.
2. **Fix it** → Forge (scripted model in tests) writes `tests/test_add_regression.py`, fixes `calc/__init__.py`
   in `forge/<id>`, runs the checks and proposes.
3. The card shows the diff, *"✓ the test fails on the old code · ✓ and passes with the fix"*, ruff, pyright and
   the full pytest suite, Critic's review and *"Sentinel: passed"*. It also waits in the approvals tray.
4. **Approve…** → the native dialog (answered "Apply" by the test, since a test can't click an OS dialog) →
   the supervisor re-checks everything, fast-forwards, tags `universe/release-1` and restarts Core. The file now
   says `return a + b`, and the card says *applied*.
5. System → Releases → **Roll back** → the dialog again → a revert commit. The file says `return a - b`, Core
   restarts, the card says *rolled back* and the issue is open again.

**Result: passes with the patch applied** (in a scratch worktree, see [Tests](#tests)). Without the patch, the
same test checks that the Forge panel says what's missing and that **Fix it** is disabled, then stops.

## What you can do now

**Report and triage**
- **Forge panel** (side panel → Forge): describe a problem in your own words, see open issues and proposals.
- **Issues come from three places:** grouped errors from every service, background jobs that keep failing,
  and your reports. They're deduplicated by fingerprint and ranked by severity and count.
- **Fix it / Ignore** per issue. Forge says plainly when it can't reproduce something, and changes nothing.

**Forge's repair loop** (SPEC §9 steps 3–8)
- **Test first:** the repro test must fail on the old code and pass with the fix, or the proposal is blocked.
- **Worktrees:** every fix lives on its own `forge/<id>` branch under `<data dir>/forge/`. Forge can't write
  protected paths, `.git`, or anything outside its worktree. Your checkout is never touched.
- **Verification** runs Core's own copy of the checks (never the worktree's): ruff, ruff format, pyright, the
  full pytest suite, and eslint + Vitest when JS changed. It runs with a scrubbed environment: no tokens,
  offline, proxies pointed at a dead port, a temporary home.
- **Reviews:** Critic reviews the code. Sentinel's deterministic review blocks protected core, deleted, renamed
  or skipped tests, removed assertions, network code outside the egress gate, raised agent permissions, and
  text aimed at the reviewers. It flags dependencies, migrations, subprocess and capture code as high risk.
- **Proposal cards:** what broke, why, the diff, the test report, both reviews, the risk, the rollback plan
  and the change's hash. At most 5 a day.
- **No apply tool exists.** Forge can propose, nothing more.

**Apply, watch, roll back** (steps 9–10, protected)
- **Approve…** opens a native dialog in Electron main with the title, root cause, risk, files, Sentinel's notes
  and the hash. Renderer code can't click it, and neither Core nor the renderer holds the supervisor's token.
- **The supervisor re-checks everything itself:** your checkout has no uncommitted changes, the branch tip is
  the verified commit, the code hasn't moved, the hash matches, and no path is protected (judged by its own
  copy of `protected-core.txt`, read at startup). Then: tag `universe/pre-release-N` → fast-forward → tag
  `universe/release-N` → restart Core → health check.
- **30-minute watch:** two Core crashes or safe mode roll the change back on their own.
- **One-click rollback** in System → Releases: revert commits, so anything you committed since stays.
- **Core's record follows the supervisor's:** Core is restarting right when there's something to record, so
  Electron main re-syncs proposals with releases each time Core comes back. That includes rollbacks the
  supervisor made on its own. Core accepts "applied" only when git agrees.

**System Vitals** (System panel, top)
- Core's heartbeat in one place: services, the models Ollama holds in memory (and how much GPU memory they
  use), the job queue, errors in the last 24 hours, Forge, and backups. Each is one line with a colour; errors
  and Forge open the Forge panel.

## Setup

From [PHASE-4.md](PHASE-4.md#setup), then:

1. The protected-core patch is applied (2026-10-21). Apply the review fixes before approving a Forge change:
   ```sh
   git apply docs/proposals/review-fixes-protected.patch
   uv run pytest tests/protected tests/unit/test_forge_core.py
   pnpm exec vitest run apps/desktop
   git add -A && git commit -m "Apply the review-fixes protected-core patch"
   ```
2. **Tell UNIVERSE where its code is:** `UNIVERSE_REPO_DIR=C:\path\to\web5` (the git checkout the app runs
   from). Without it, Forge says so and stays off.
3. **A large local model with tools** for Forge (`local-large`; System → Recommended models suggests one for
   your hardware, e.g. a Qwen3 coder). Small models can drive the loop but write weaker fixes.
4. No new dependencies: Forge uses git, uv and pnpm, which you already have.

## Demo script (≈10 minutes)

1. Apply the patch (Setup 1), set `UNIVERSE_REPO_DIR`, run `pnpm dev`.
2. **Inject a bug** in a scratch copy, so your real checkout stays clean:
   `uv run python -c "from pathlib import Path; from tests.support.forge_repo import make_repo; print(make_repo(Path('C:/Temp/forge-demo')))"`
   (it prints `C:\Temp\forge-demo\app`), then point `UNIVERSE_REPO_DIR` at that folder and restart. Its `calc.add()` subtracts.
3. **Forge panel → Report a problem:** *"add(2, 3) returns -1 instead of 5"* → **Report to Forge**.
4. **Fix it.** Follow Forge in Agents → Tasks: it searches, reads, writes the failing test, fixes, runs the
   checks and proposes. (A few minutes with a real model.)
5. Open the card: the diff, the test that failed first, the checks, Critic and Sentinel.
6. **Approve…** → read the native dialog → **Apply**. Core restarts; the card turns *applied*. `git log` in the
   scratch repo shows `universe/release-1`.
7. **System → Vitals:** Forge idle, errors none. **System → Releases:** *watching*.
8. **Roll back** → confirm. The file is back to `a - b`, the card says *rolled back*, the issue is open again.
9. **Try to sneak something past it:** report a bug and, while Forge works, watch Sentinel block anything that
   touches `protected-core.txt` or skips a test (or read `tests/protected/test_sentinel.py`).

## Tests

| Suite | Count | New in Phase 5 |
| --- | --- | --- |
| pytest, main (`uv run pytest`) | 253 collected (1 Windows-only skip) | Forge core: protected paths (case-insensitive), worktrees, writes outside the worktree, no apply/merge/approve tool exists, verification (fails on base, passes on head), per-proposal base checkouts, triage and dedup, the daily cap and no orphan worktree on refusal, the API, Core checking "applied" against git and refusing a stale source state idempotently; the Forge loop end to end on a scratch repo with the scripted model; loaded models |
| pytest, with the patch | 273 collected (1 Windows-only skip) | + 10 Sentinel tests and 10 release tests (apply checks, dirty checkout, moved branch, wrong hash, protected paths judged by the supervisor's own manifest copy — including a rename to an unprotected path, network/approval block rules, rollback keeping later commits, a release that makes Core crash and rolls itself back) |
| Vitest | 121 (129 with the patch: + 8 approval-dialog tests) | System Vitals, the approval dialog: refuses what isn't ready, applies only after the dialog, reports refusals, rollback, and Core catching up after a restart |
| Playwright Electron | 23 without the patch: 22 passed, the Phase 5 done-when stops after checking the missing-patch path · with the patch, `app.spec.ts` + `safe-mode.spec.ts`: 15 of 15 passed | the Phase 5 done-when (with the patch: the full loop; without: the missing-patch path), System Vitals |

Everything listed passed here: `ruff`, `ruff format`, `pyright`, `eslint`, `prettier`, `tsc`, the
generated-types check and `pnpm build`. The e2e suites ran under `xvfb-run`.

The real-Ollama tests ran too (an `ollama` binary is on this machine): they passed in every idle run. Twice
the chat test missed its 60-second budget while I was running other heavy jobs at the same time; I reproduced
that with busy loops on every core (llama.cpp slows down sharply when its threads have to share cores). The
reply normally takes about 3 s. The test is unchanged; [HANDOFF.md](HANDOFF.md#environment-notes-learned-the-hard-way)
now says not to run heavy jobs alongside it.

### Bugs found and fixed while building Phase 5

- **The card stayed "ready" after a successful apply.** The supervisor restarts Core right after applying, so
  Electron main's "applied" record hit a Core that was down (`ERR_CONNECTION_REFUSED`). Main now re-syncs with
  the supervisor's releases each time Core comes back. That also records the supervisor's own automatic
  rollbacks, which nobody told Core about before. Regression tests in `forge.test.ts`; the done-when e2e now
  requires *applied* and *rolled back* on the card.
- **The next test after a rollback could hit a restarting Core.** The done-when test ended on a stale "Core
  online"; it now waits for the card to say *rolled back*, which needs the restarted Core.

### Readiness-audit fixes (2026-10-18)

A multi-dimension audit of everything Phase 5 adds confirmed 13 issues (no blockers), all fixed with regression
tests. The safety-relevant ones:

- **Concurrent Forge verifications could falsely pass.** Two proposals off the same base commit shared one base
  checkout dir, so one's `git clean`/`checkout` could wipe the other's repro file mid-run, recording a spurious
  *fails-on-base* and passing verification with no real failing test. Base checkouts are now keyed per proposal.
- **Sentinel's network block was narrower than the project's own egress rule** (it missed `http.client`). It now
  matches `tests/protected/test_invariants` and adds the JS clients, and it flags an agent narrowing its
  `requires_approval`.
- **A rename could carry a protected file out.** The supervisor's protected-path gate used git with rename
  detection on, which shows only the (unprotected) destination; it now uses `--no-renames` and refuses the
  protected source. The pre-release tag is created only after the fast-forward merge succeeds.
- **`record_release` hardening:** the "applied" record is idempotent (main re-syncs after a Core restart) and
  refuses a rejected/rolled-back proposal; the Windows `.venv` symlink falls back to a junction; the protected
  matcher is case-insensitive; the vacuous `services/sentinel/**` manifest glob became a comment pointing at the
  real `protected/sentinel.py`.

Deferred (documented, not a blocker): the supervisor holds its lock across the release's git subprocesses — fine
for a rare, owner-initiated apply; restructuring the lock was judged riskier than the nit.

## Known limitations

- **Sentinel's written (model) review is deferred.** Sentinel's verdict is the deterministic code review, which
  is what gates a proposal and what the UI shows. The `sentinel.yaml` agent's short *prose* review (ADR-0014)
  isn't wired into `propose()` yet — only Critic's prose is. The deterministic review is the substantive part;
  the agent note is a later nicety.
- **Verification isn't isolated (flag, security).** It runs Forge's code as a normal process with a scrubbed
  environment. That limits accidents, not a determined attacker. Containers are the fix (ARCHITECTURE §2.2,
  still your decision). Sentinel's review and your approval stand in front of it either way.
- **Verification runs lint, types and the unit and integration suites.** It doesn't yet run agent evals, perf
  benchmarks or the Electron e2e suite (SPEC §9 step 6 asks for evals and benchmarks; they arrive with Forge v2
  in Phase 11, when there's an eval set to run).
- **Applying restarts Core only.** A fix in the UI or Electron main needs `pnpm build` and an app restart to
  show (the supervisor doesn't rebuild the app). Packaged installs and a runtime checkout come in Phase 12.
- **The watch looks at crashes and safe mode,** not error rates or performance. Until the review-fixes patch is
  applied, two restarts you ask for during the watch also count as crashes and roll the release back.
- **A rollback that conflicts with your later edits** (the same lines) is left to you. With the review-fixes
  patch, it changes nothing and shows `rollback_failed` in System → Releases. Without it, the checkout is left
  mid-revert.
- **Schema migrations:** Sentinel flags them high risk, and Core snapshots the database before migrating.
  There's no check that a restic backup is recent before applying yet.
- **Not built yet from SPEC §9:** a scheduled test run that files failing tests as issues (the issue type
  exists; nothing runs it yet), perf-regression detection, Observer screenshots of error dialogs (Phase 8),
  the optional auto-apply toggle (off by default anyway), and showing the codebase as a galaxy.
- **Forge needs `UNIVERSE_REPO_DIR`** and a clean checkout to apply. It refuses rather than stashing your work.
- **Linux as root:** Electron needs `--no-sandbox` (as before); Windows doesn't.
- **Not yet run on Windows** (CI jobs still get no runner).

## What's next: Phase 6 (Research)

SPEC §25: SearXNG, fetch and extract, citations, cache, quick and deep modes, watchlists, save to vault,
injection defenses. Done when a deep-research report with cited sources lands in the vault. It's the first
phase that goes online, through the egress gate, so expect a privacy and egress review first.

Useful from you now:
- apply the [review fixes](proposals/review-fixes-protected.md), then approve Phase 5;
- try the demo on the scratch repository, then point Forge at a real issue;
- run `pnpm bench:universe` on your PC if you haven't yet (Phase 4).
