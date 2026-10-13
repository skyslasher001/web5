# Proposal: Phase 3 protected core — policy engine, permission rules, budget caps, kill switch

Status: **waiting for the owner** (proposed 2026-10-13). Apply it yourself, or tell the assistant "apply the Phase 3 patch".

Patch: [`phase-3-protected-core.patch`](phase-3-protected-core.patch), 13 files, about 950 added lines. Design: [ADR-0011](../adr/0011-phase-3-agent-engine.md).

## Why this needs you

The agent engine is built and committed. Everything that *decides* what agents may do belongs to protected core (AGENTS.md, `protected-core.txt`): the permission engine, budget caps, the kill switch, the supervisor, Electron's protected main code and `tests/protected/`. The assistant may not write those paths, so they arrive as this patch.

Until it's applied, agents behave as in Phase 1: they chat without tools. The UI says so, the engine's tests are skipped with that reason, and everything else works.

## What it adds

| Where | What |
| --- | --- |
| `services/core/.../protected/policy.py` | **The policy engine.** Every agent model call and tool call goes through it. Model calls check the kill switch, budget caps, and the agent's step, token and time limits. Tool calls are decided in this order: kill switch → tier gate (an agent can never use a tool above its `permission_tier`) → your rules → taint (after an agent has read your files, anything with side effects or network access asks first) → defaults (read: allow; write: ask if listed in the agent's `requires_approval`; system: always ask; MCP tools: ask until you set a rule). |
| `.../protected/permissions.py` | **Your permission rules.** Allow, ask or deny, per agent (or all agents) and per tool or glob, optionally with an expiry. The most specific rule wins, and between equally specific rules the strictest wins. Only your UI session can add or remove rules, and every change is audited. |
| `.../protected/budget.py` | **Budget caps.** Reads month-to-date spend from the usage ledger. Local calls cost $0 and always pass. The default cap is $0, so no paid model can run until you raise it. Warnings at 50 % and 80 %, a stop at 100 %. Only your UI session changes caps. |
| `.../protected/killswitch.py` | **The kill switch, Core side.** The state lives in `<data dir>/killswitch.json`. When engaged, every agent call is refused, running tasks are cancelled, pending approvals are refused and the egress gate closes. A restarted Core comes back still engaged, and an unreadable state file counts as engaged (fail safe). |
| `services/supervisor` (`control.py`, `supervisor.py`, `health.py`) | **`POST /killswitch {engaged}`** on the supervisor's control port. It writes the state file and tells Core to apply it. If Core doesn't confirm within 1 s (hung), the supervisor restarts it, and it comes back engaged. Standard library only, as before. |
| `apps/desktop/src/main/protected/killswitch.ts`, `supervisor.ts`, and `index.ts` wiring | **The control in Electron main.** The hotkey is **Ctrl+Alt+Shift+K**; there is also a tray item and the HUD button. Engaging is instant and stops capture locally first (no capture exists before Phase 7). **Releasing needs a native dialog** that no renderer code, and nothing in Core, can click. Core's own API can engage but never release. |
| `tests/protected/test_policy.py`, `test_killswitch.py`, `killswitch.test.ts` | 14 Python and 3 Vitest tests covering every rule above, including a hung Core being restarted engaged. |

## How it was tested

- In a scratch worktree at the main branch's head with this patch applied: the full Python suite passes (198 tests, 1 Windows-only skip), including the 8 agent-engine tests that are skipped without it. The patch also applies cleanly to a fresh checkout of the main branch's head.
- The Phase 1 chat tests were run with the policy installed. That found four places where chat through the engine behaved differently: event order, a stopped reply losing its partial text, a provider failure losing its error code, and chat failing with models that can't call tools. All four were fixed in unprotected code before this proposal.
- The desktop typecheck, eslint, prettier and the 28 desktop Vitest tests pass with it.
- With the Phase 3 UI on top (rechecked 2026-10-13): the full Electron e2e run passes with it (13 tests), including the done-when flow with an approval card and the kill switch released through its native dialog. On the main branch without it, the same run passes with those two tests skipped.

## To apply it

```sh
git apply docs/proposals/phase-3-protected-core.patch
uv run pytest tests/protected tests/integration/test_agent_engine.py
pnpm exec vitest run apps/desktop
git add -A && git commit -m "Apply the Phase 3 protected-core patch"
```

## What to look at closely

- The defaults in `policy.py` (`check_tool`): they decide what runs without asking you.
- The release path in `index.ts`: the native dialog is the only way to release the kill switch.
- The `$0` default budget cap.
