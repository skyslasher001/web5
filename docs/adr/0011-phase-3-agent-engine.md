# 0011 — Phase 3 agent engine: loop, approvals, protected policy, minimal MCP client

- Status: Accepted
- Date: 2026-10-13
- Flags: security, architecture, privacy

## Context

Phase 3 (SPEC §25) adds the agent engine: a YAML registry, the Core orchestrator, the first agents (Navigator, Librarian, Scribe, Critic), tools with permission tiers and an approvals tray, an MCP client, memory, the audit log, a model router with budget caps, and the kill switch. ADR-0004 chose a custom loop. Several pieces sit in protected core (the policy engine, permission rules, budget caps, kill switch), which this assistant may not write: they ship as a patch for the owner to apply.

## Decision

1. **Where the code lives.**
   - `services/agents`: the loop (`runtime.py`), the tool interface (`tools.py`) and the tool-calling provider. No database or Core imports, so it's testable on its own.
   - `services/core`: the stores (tasks, steps, approvals, usage, memories, MCP servers), the built-in tools, delegation and Critic review (`agent_engine.py`, `agent_tools.py`, `memory.py`, `mcp_client.py`).
   - `services/core/src/universe_core/protected/` (owner-applied patch): `policy.py` (every LLM and tool call), `permissions.py` (rules, written only from your UI session), `budget.py` (caps), `killswitch.py`. The supervisor's `POST /killswitch` and Electron main's kill-switch hotkey are in the same patch. Until it's applied, Core runs agents chat-only (Phase 1 behaviour) and says why.
2. **One loop, deterministic gates.** Each step: policy `check_llm` (kill switch, budget caps, step/token/time limits) → model call (streamed) → for each tool call: validate arguments, policy `check_tool` → run, park for approval, or refuse → record a `task_steps` row, an event and an audit entry (tool name and an arguments hash, never content). The same tool with the same arguments three times in a row stops the task.
3. **Approvals wait in memory.** A task that needs approval parks on an asyncio future until you decide in the tray (24 h expiry). If Core restarts, waiting and running tasks are marked failed ("interrupted by a restart") rather than resumed: resuming mid-plan safely needs the whole context replayed, which isn't worth the risk yet.
4. **Taint.** Tools that return text from files, the web or MCP mark their results untrusted. The text is quoted with provenance, and from then on the policy asks before any tool with side effects or network access.
5. **Orchestration.** Core delegates to specialists through an `agent.delegate` tool (one level deep). When a task changed something (a side-effect tool ran), Critic reviews the final answer before it's shown, and the review is part of the trace.
6. **Memory.** A `memories` table with FTS5. Agents may save memories in their own scope directly; anything about you (`self`) or shared with all agents is saved as `proposed` and needs your approval. Relevant memories are added to an agent's context with their provenance. Vector recall waits for the brain layer (Phase 9).
7. **Model routing.** Agents with tools get a model that lists the `tools` capability. Every model call goes into `usage_ledger` (local calls cost $0 but are counted), which the budget caps read.
8. **MCP: a minimal stdio client of our own** (`initialize`, `tools/list`, `tools/call`), not the official SDK. The SDK (`mcp` 2.3.0, MIT; pinned at 2.2.0 here) pulls in httpx2, Starlette, Uvicorn, PyJWT with cryptography, OpenTelemetry and pywin32 for transports we don't use. It is a **dev-only** dependency, used to run a real MCP server in tests so our client is checked against an independent implementation. MCP tools are tier `write`, have side effects, and return untrusted text, so they ask first until you add a rule. Servers are added only from your UI session; each one is a program you choose to run.

Checked for this decision (2026-10-13): `mcp` 2.2.0/2.3.0 is MIT, Python ≥ 3.10. The `@modelcontextprotocol/server-*` npm packages 1.0.0 ship no LICENSE file (only "SEE LICENSE IN LICENSE") and bundle jszip (MIT or GPL-3.0), so they aren't used even in tests.

## Consequences

- The safety-critical decisions (tiers, rules, taint consequences, caps, kill switch) live in protected code, so Forge can't weaken them and the owner reviews them once.
- **Flag (security):** an MCP server is a local program with your user's rights. Its own network access doesn't pass through the egress gate. Adding one is a UI-only, audited action, and its tools always start as "ask".
- Phase 3 needs a model that supports tool calling (for example `qwen3:8b`). Without one, agents answer without tools and the UI says so.
- Tasks don't survive a restart (see 3).

## Alternatives considered

- **Official MCP SDK at runtime:** less code of ours, much more dependency weight and attack surface in Core.
- **Persisting full task state to resume after a restart:** more robust for hours-long approvals, but replaying a half-finished plan is its own risk. It can come later with a resume button.
- **Policy outside protected core:** would let the engine land without an owner step, but then Forge could change the rules that bind it. Rejected.
