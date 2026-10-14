# 0014 — Phase 5: Forge and Sentinel v1

- Status: Accepted
- Date: 2026-10-14
- Flags: security, architecture

## Context

SPEC §9 and §25 Phase 5: Forge repairs UNIVERSE (triage, failing-test repro, patching in worktrees,
verification, review, approval cards, apply and rollback, post-apply health watch) and never weakens safety.
ARCHITECTURE §7 holds the safety design. Done when: *"I inject a deliberate bug, Forge finds it and proposes a
tested fix, I approve, it applies, and one-click rollback works."*

Much of this is protected core (`protected-core.txt`): Sentinel (`services/sentinel/**`,
`agents/sentinel.yaml`), Forge's own definition (`agents/forge.yaml`), the supervisor (apply, rollback, watch),
and Electron main's protected code (the native approval dialog). As in Phase 3, those parts ship as a patch
the owner applies (`docs/proposals/phase-5-protected-core.md`), tested in a scratch worktree.

## Decision

**Split by who may change it**

| Part | Where | Protected |
| --- | --- | --- |
| Issues and triage: grouped errors, failed jobs, failing checks, your bug reports | Core `forge.py` | no |
| Worktrees `forge/<id>` under `<data dir>/forge/`, file writes that refuse protected paths, `.git` and anything outside the worktree | Core `forge.py` | no |
| Verification: the repro test must fail on the base commit and pass on the patch; then lint, types and the test suites | Core `forge_verify.py` | no |
| Proposals (diff, diff hash, root cause, test report, reviews, risk, rollback plan, status) and their REST API | Core `forge.py`, `forge_api.py`, migration 0007 | no |
| Forge's tools: read and search the repo, open a worktree, write in it, run checks, propose. **No apply or approve tool exists.** | Core `forge_tools.py` | no |
| Forge's agent definition and limits | `agents/forge.yaml` | **yes** |
| Sentinel's deterministic diff review: protected paths, test integrity, new dependencies, new network or subprocess code, agent permission changes, consent and capture code, migrations; and the daily proposal cap | `services/sentinel/` | **yes** |
| Apply: re-check against the supervisor's own manifest copy, refuse a dirty checkout, tag, fast-forward merge, restart, health check, watch window, automatic rollback | supervisor `releases.py` | **yes** |
| The native approval dialog (summary and diff hash) that alone can trigger apply | `apps/desktop/src/main/protected/forge.ts` | **yes** |
| Approval cards, the System Vitals panel, releases and one-click rollback in the UI | `apps/ui` | no |

**Without the patch** there is no Forge agent (its YAML is protected), no Sentinel and no apply. Everything
else is in place and tested: issues and triage, the worktree and verification machinery, proposals, and the UI,
which says what's missing. A proposal can only be approved once it has Sentinel's verdict.

**Rollback never loses work.** Apply refuses a checkout with uncommitted changes. Rollback adds a revert
commit (or checks out the previous release tag on a detached runtime checkout) rather than rewriting history.

**The model.** Forge uses the large local tier with tools (`local-large`, e.g. a Qwen3 coder or Gemma 4
model the System panel recommends). Tests drive it with the scripted fake model, like every other agent.

## Consequences

- **Flag (security):** verification runs code Forge wrote. Until containers exist (ARCHITECTURE §2.2,
  Podman on WSL2, still an open question), it runs as a subprocess with a scrubbed environment (no tokens,
  `UNIVERSE_OFFLINE=1`, proxies pointed at a dead port, a temporary home), with timeouts, inside the
  worktree. That limits accidents, not a determined attacker. Two mitigations hold regardless: Sentinel's
  deterministic review runs on the diff before verification, and Forge's input (logs, errors) is marked
  untrusted, so prompt injection can at worst produce a bad proposal that still faces verification,
  review and you. Real isolation is a Phase 12 or earlier decision for you.
- Proposals keep everything forever: the diff, test output, reviews and your decision.
- The daily cap (5) and duplicate suppression (by error fingerprint) keep Forge quiet.

## Alternatives considered

- **Forge applies its own patches with a confirmation in the renderer:** a compromised renderer or Core could
  click it. The native dialog in Electron main, and the supervisor token only main holds, close that path.
- **A new git clone per proposal:** slow and heavy; worktrees share the object store.
- **Rollback by `git reset --hard`:** would discard anything you committed meanwhile.
