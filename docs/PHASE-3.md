# Phase 3: Agent engine

Status: **delivered 2026-10-13, approved 2026-10-13.** Phase 4 (Universe interface) is in progress. The protected-core part (policy engine, permission rules, budget caps, kill switch) was approved and applied on 2026-10-13: [proposals/phase-3-protected-core.md](proposals/phase-3-protected-core.md).

Phase 3 turns Core from a chat partner into an orchestrator. It can hand work to specialists, use tools on your vault, ask you before it does anything that matters, remember what you let it remember, and leave a tamper-evident record of everything. Design decisions are in [ADR-0011](adr/0011-phase-3-agent-engine.md).

**Done when** (SPEC §25): *"find my notes about X, summarize them, and link them to project Y" works end to end with a full audit trail.* Two tests do exactly that:

- `tests/integration/test_agent_engine.py::test_find_summarize_and_link_with_a_full_audit_trail`, through Core's REST API: Core delegates the search to the Librarian, the Librarian searches and reads both notes, Core asks you before linking them (it read your files, so the task is *tainted*), you approve, the two notes join the galaxy, Critic checks the answer, and the audit log has `task.started`, every `tool.call`, `approval.decided`, `item.linked` and `task.finished`. The log holds ids and hashes, never the text of your notes, and its hash chain verifies.
- `tests/e2e/app.spec.ts` (*done when: find notes, summarize them…*), the same flow in the real Electron app: type the request in the Agents panel, approve the card that appears, read the summary with *Checked by Critic*, follow the trace, and verify the audit log in the Safety panel.

Both run against the protected policy engine, which is now applied. (If `protected/policy.py` were ever missing, they'd skip with that reason and agents would chat without tools, as in Phase 1.)

## What you can do now

**Give agents work**
- **Chat with Core** as before. When a request needs your vault, Core uses its tools and the chat shows what it's doing (*Searching your vault…*, *Waiting for your OK…*). Each reply has a *View trace* link.
- **Agents panel** (`A`, or click a specialist in the dock): pick an agent, type an instruction, *Run*. Tasks are listed with their status; open one for its trace: every model call, tool call, decision and duration, the specialists it asked, the output, and a *Stop* button while it runs.
- **Five agents:** Core (orchestrator), Navigator (finds and shows things in UNIVERSE), Librarian (searches, reads and organizes your vault), Scribe (writes notes) and Critic (reviews answers that changed something). Each is a YAML file in `agents/` with its tools, permission tier, limits and prompt.
- **Navigator moves the HUD:** when an agent shows you a galaxy, an item or a search, UNIVERSE goes there.

**Stay in control**
- **Approvals tray:** when an agent wants to do something that needs your OK, a card appears at the top: who asks, what exactly ("Add 2 item(s) to the galaxy 'DevMind'"), why it's asking, and the risk. *Approve*, *Decline* or *Always allow* (a permission rule). Unanswered approvals expire after 24 hours.
- **The defaults** (protected policy engine): reading is allowed; writing asks when the agent's YAML lists the tool under `requires_approval`; system actions always ask; MCP tools ask until you set a rule. After a task has read your files or other outside text, anything with side effects or network access asks, even with an *allow* rule, unless the rule says *even after reading files*. An agent can never use a tool above its tier.
- **Permission rules** (Safety panel): allow, ask or never, per agent or for all, per tool or glob (`mcp.github.*`). The most specific rule wins; between equals, the strictest.
- **Kill switch:** `Ctrl+Alt+Shift+K`, the tray, the top-bar button or the palette. Every agent stops at once, pending approvals are refused and outbound network closes. A red banner stays up, even in zen mode. Releasing it needs a native confirmation dialog; nothing in the interface or in Core can release it on its own. It survives a restart.
- **Guardrails:** step, token and time limits per agent (in its YAML); a task that repeats the same tool call three times is stopped; unknown tools and malformed arguments are refused and shown in the trace.

**Memory**
- Agents keep notes in their own scope directly. Anything about you, or shared with every agent, arrives as a **proposal** (Agents → Memory) that you keep or discard. You can add, edit and forget memories yourself. Relevant memories go into an agent's context marked as notes, not instructions.

**Money and records**
- **Budget meter** in the top bar: spend this month against your cap. Local models cost $0 and always run; the default cap is $0, so no paid model can run until you raise it (Safety → Budget). Warnings at 50 % and 80 %.
- **Audit log** (Safety → Audit log): every task, tool call, approval, rule change and kill-switch use, hash-chained. *Verify* checks the chain.
- **MCP servers** (Safety → MCP servers): add a local tool server by name and command (for example `uvx mcp-server-time`). Its tools appear as `mcp.<server>.<tool>`, ask first, and their output is treated as untrusted.

## Setup

From [PHASE-2.md](PHASE-2.md#setup), then:

1. `uv sync` and `pnpm install` (new: the MCP SDK as a dev-only test dependency).
2. **A model that can call tools.** `gemma4:e4b`, the Phase 1 default, lists `tools` on Ollama's registry. If yours doesn't, chat still works without tools and the hint says what to pull, for example `ollama pull qwen3:8b`. Choose it in System → Chat model.
3. `pnpm dev`.

## Demo script (≈5 minutes)

With a tool-capable model:

1. `pnpm dev`. The dock lists five agents. The top bar has the budget meter (`$0.00 · local`) and the kill-switch button.
2. **Some notes:** press `Ctrl+Space`, `Tab`, write `The Austin land deal closes in November #deals`, `Ctrl+Enter`. Add a second: `A land deal by the lake: the owner is motivated.`
3. **The done-when request:** press `C` and type `Find my notes about land deal, summarize them, and link them to project DevMind.` The orb and the chat say what Core is doing: *Asking a specialist…*, *Searching your vault…*, then *Waiting for your OK…*
4. **Approve:** the card at the top says *Core asks to project.add_items: Add 2 item(s) to the galaxy 'DevMind'*, and why it's asking. Click *Approve*. The reply arrives with the summary, *Added 2 item(s) to DevMind* and *Checked by Critic*.
5. **The trace:** click *View trace*. Every step, with the Librarian's search and reads under *Specialists*. Open a step to see its arguments or result.
6. **The galaxy:** `Ctrl+K` → *Go to DevMind*. Both notes are there.
7. **The audit trail:** Safety → Audit log → *Verify*: *Intact*. The entries name tools and ids, not your text.
8. **A rule:** Safety → Permission rules: Core, `project.add_items`, Allow, tick *even after reading files*, *Add rule*. Ask the same question for project *UNIVERSE*: no card this time.
9. **Memory:** in chat, `Remember that I prefer short summaries.` Agents → Memory shows a proposal. *Keep* it.
10. **Kill switch:** press `Ctrl+Alt+Shift+K`. The red banner appears; ask Core something and the task fails with *kill switch*. *Release…* asks you in a system dialog.

## Tests

| Suite | Count | New in Phase 3 |
| --- | --- | --- |
| pytest (`uv run pytest`) | 200: 199 passed, 1 Windows-only skip | the tool-calling provider (streamed fragments, usage), the router's tool capability, the agent runtime and guardrails, delegation and Critic review, approvals, memory scopes, the MCP client against the official SDK server, chat through the engine, and the done-when |
| Vitest (`pnpm exec vitest run`) | 70 | step labels, activity lines for approvals and the kill switch, which views an event refreshes, the agent API client, the kill-switch control in Electron main |
| Playwright Electron (`pnpm test:e2e`) | 13 | the agent dock and panels, the done-when with an approval and the audit trail, the kill switch and its native release dialog |

Run here (Linux, Python 3.12, Node 22) after applying the protected-core patch: pytest 199 passed (1 Windows-only skip), Vitest 70, and all 13 e2e tests passed. Before it was applied, the same suites passed with the patch-only tests skipped (Vitest 67, e2e 11 + 2 skipped). `ruff`, `ruff format`, `pyright`, `eslint`, `prettier`, `tsc` and the generated-types check are clean.

### Bugs found and fixed while building Phase 3

Each has a regression test.

- Chat through the engine broke four Phase 1 behaviours: the reply's events arrived in a different order, a stopped reply lost its partial text, a provider failure lost its error code and hint, and chat failed outright with a model that can't call tools (it now falls back to a plain reply).
- The fake model reused tool-call ids, so two results overwrote each other in the transcript; ids are unique now, as real servers send them.
- MCP tools were allowed by default like built-in reads. They ask first now: they're someone else's code.
- Specialists' sub-tasks each put a "finished" line in the activity ribbon; only the task you started does now.

## Known limitations

- **No real tool-calling model was run here.** Ollama's registry is unreachable from the build environment, so the engine is tested with a scripted stand-in model that speaks Ollama's OpenAI-compatible tool-calling protocol. Small local models call tools less reliably than the stand-in; one report says Gemma 4's tool calls get unreliable after 3–4 in a row on older Ollama versions. Try `qwen3:8b` if Core stalls or ignores its tools.
- **Tasks don't survive a restart.** A task running when Core restarts is marked failed, and its pending approval expires. Run it again.
- **One level of delegation**, by design: specialists can't delegate further.
- **Memory search is keyword-only** (FTS5). Vector recall comes with the brain layer (Phase 9).
- **MCP:** stdio servers only, no resources or prompts, and the command field splits on spaces (no quoting). An MCP server is a program running with your rights; its own network access doesn't go through the egress gate (flagged in ADR-0011).
- **Paid providers aren't wired yet**, so the budget only ever counts $0 local calls. The cap and warnings are in place for when they are.
- **Not yet run on Windows**, as in Phase 2: CI still ends in `startup_failure` before any job runs. Untested there in particular: the kill-switch global shortcut and the native release dialog.
- **The `pre-universe` tag** still isn't on GitHub.

## What's next: Phase 4 (Universe interface)

Delivered 2026-10-14: see [PHASE-4.md](PHASE-4.md).


SPEC §25: the 3D universe on real data, celestial mapping, four layouts, zoom levels with LOD, the complete HUD, item viewers, agent probes, constellation results, quality presets and Lite mode. Useful from you now: review Phase 3, try the demo with `gemma4:e4b` or `qwen3:8b`, and fix the Actions setting so Windows CI runs.
