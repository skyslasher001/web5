# GitHub Copilot instructions

Follow [`AGENTS.md`](../AGENTS.md) at the repository root: it holds this project's rules, commands, layout and
current phase, and it is the single source of truth for every AI assistant. Read it, then `SPEC.md`,
`docs/ARCHITECTURE.md` and the newest `docs/PHASE-*.md`, before changing anything. How to pick up the work is in
[`docs/HANDOFF.md`](../docs/HANDOFF.md).

The hard rules, in short (details in `AGENTS.md`): never edit the paths in `protected-core.txt` (propose a
patch in `docs/proposals/` instead); never disable, skip or weaken a test; never delete or rewrite vault data;
no secrets; outbound network only through the egress gate; generated files only via `pnpm tokens` and
`pnpm gen:types`.
