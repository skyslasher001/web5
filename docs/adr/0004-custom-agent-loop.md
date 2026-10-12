# 0004 — Custom agent loop instead of PydanticAI

- Status: Proposed
- Date: 2026-10-12
- Flags: security, architecture

## Context

SPEC §22 offers "lightweight custom loop or PydanticAI". The agent runtime must enforce permission tiers, pause a task for hours while it waits for approval, track taint from untrusted content, stop at budget caps, obey the kill switch instantly, and write every step to the audit log and the trace.

## Decision

A custom loop (~400 lines) in `services/agents/runtime`:

- Providers: the OpenAI-compatible chat API (`openai` SDK) against Ollama, llama.cpp or opt-in cloud, via the model router and broker.
- Tools: a `Tool` protocol with Pydantic input models (JSON Schema for the LLM), tier, side-effect and network flags, and a timeout. MCP servers are wrapped as tools using the official `mcp` SDK.
- Every step does a budget check → LLM call → for each tool call, `policy.check()` → run, or create an approval and park the task as `waiting_approval` → record a `task_steps` row → emit events.
- Guardrails: step, token, time and money limits, loop detection (repeated tool + args hash), retries with backoff.
- Orchestration: Core plans, delegates subtasks to specialists in parallel, and routes important outputs through Critic.

## Consequences

- The safety-critical path is our code, visible to tests and to Sentinel. The policy engine itself is protected.
- We maintain the loop and its provider quirks (tool-call formats differ slightly between local models). An eval suite per agent catches regressions.

## Alternatives considered

- **PydanticAI:** MIT, good typed tools and MCP support, deferred-tool approvals. We'd still need to wrap every call for taint, budget, kill switch and audit, and hours-long parked tasks fit awkwardly in its run model. It can be revisited if the loop grows past ~1k lines.
- **LangGraph and similar:** heavier abstractions than the problem needs.
