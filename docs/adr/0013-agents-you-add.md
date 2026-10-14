# 0013 — Agents you add: the roster, custom agents and turning agents off

- Status: Accepted
- Date: 2026-10-14
- Flags: security

## Context

The owner asked for an Agents tab: every agent with a short synopsis and its stats, and the ability to add and
remove agents. Until now the agents were the YAML files in `agents/`, shipped with the app (SPEC §8), and
`agents/forge.yaml` and `agents/sentinel.yaml` are protected core.

## Decision

- **Built-in agents stay as shipped.** The app never edits `agents/*.yaml`. "Removing" a built-in turns it off
  (setting `agents.disabled`), and it can be turned back on. A synopsis edit for a built-in is stored in
  settings (`agent.synopsis.<id>`).
- **Your own agents live in `<data dir>/agents/`** (`<id>.yaml` and `prompts/<id>.md`), validated by the same
  schema as the built-ins, so app updates never clash with them. Removing one moves its files to
  `<data dir>/agents/.removed/`; nothing is deleted.
- **Can't be turned off:** Core (it runs every task) and Critic (it reviews every task that changes something),
  plus Forge and Sentinel (protected core) once they exist.
- **What your own agents may have:** read or write access (not system), the fast or large local model, and only
  tools that exist, except `agent.delegate` (only Core orchestrates). Every tool call still goes through the
  protected policy engine: the tier gate, your permission rules, taint and approvals. Adding, changing and
  removing agents is written to the audit log.
- **The live agent set** (the dict the engine and chat share) is updated in place, so a change applies to the
  next task. Core's context lists the specialists that are on, so it can delegate to an agent you added.
- **Stats** come from `agent_tasks`: tasks, done, failed, cancelled, success rate, average steps, tokens, cost,
  last active.

## Consequences

- **Flag (security):** an agent you add gets tools. The risk is bounded by the policy engine, which sees a
  custom agent exactly like a built-in one at the same tier, so a custom agent can do nothing a built-in agent
  at that tier couldn't.
- Disabled agents keep their history, memories and permission rules; turning one back on restores it as it was.
- A broken file in `<data dir>/agents/` is logged and skipped; it never stops Core.

## Alternatives considered

- **Writing new agents into `agents/`:** mixes the owner's agents with shipped code (and git); an update would
  conflict with them.
- **Deleting built-in YAML on remove:** loses them on the next update anyway, and would let the app remove
  Core or Critic.
