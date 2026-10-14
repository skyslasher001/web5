# Handoff: working on UNIVERSE with any AI assistant

This page lets any AI coding assistant (or a person) pick up UNIVERSE where the last one stopped. Claude Code,
Codex, Copilot, Cursor, Windsurf, Cline, Gemini CLI and Aider all work from the same rules. Nothing here is
tool-specific except the [table of instruction files](#which-file-each-tool-reads).

**One source of truth:** [`AGENTS.md`](../AGENTS.md) holds the rules, the commands, the layout and the current
phase. Every tool-specific file only points to it. When something changes, change `AGENTS.md`, never a copy.

## Start prompt

Paste this into a new session of any assistant:

> You're working on UNIVERSE, a local-first desktop "digital brain". Before doing anything, read `AGENTS.md`,
> then `SPEC.md`, `docs/ARCHITECTURE.md` and the newest `docs/PHASE-*.md`, then `docs/HANDOFF.md`. Tell me in
> five lines: the current phase and its status, what's waiting on me, and what you'd do next. Don't change any
> file until I say go. Follow `AGENTS.md`'s hard rules exactly: never edit the protected core
> (`protected-core.txt`; write a patch in `docs/proposals/` instead), never weaken a test, never touch real
> vault data, no secrets, outbound network only through the egress gate.

To deliver a phase: *"Deliver Phase N"* means build exactly that phase's scope from SPEC §25 and stop, with
setup steps, tests, a demo script, known limitations and what's next in `docs/PHASE-N.md` (see
[How a phase is delivered](#how-a-phase-is-delivered)).

## Where things stand

The **Current phase** line in [`AGENTS.md`](../AGENTS.md#read-first) is kept up to date. The newest
`docs/PHASE-*.md` has the details: what works, the test counts, known limitations, what's next. Open
protected-core patches waiting for the owner are in [`docs/proposals/`](proposals/); each has a status line.

Read in this order:

| # | File | Why |
| --- | --- | --- |
| 1 | [`AGENTS.md`](../AGENTS.md) | Rules, commands, layout, current phase |
| 2 | [`SPEC.md`](../SPEC.md) | The requirements: every line is one. §25 lists the phases and their "done when" |
| 3 | [`docs/ARCHITECTURE.md`](ARCHITECTURE.md) | The design, with "as built" notes where the build differs |
| 4 | Newest [`docs/PHASE-*.md`](.) | What exists now and what's open |
| 5 | [`docs/adr/`](adr/) | Why each decision was made (template in `adr/README.md`) |
| 6 | [`docs/proposals/`](proposals/) | Protected-core changes waiting for, or applied by, the owner |

## How to work here

**The loop for any change**
1. Read the relevant SPEC section, the ARCHITECTURE section and the code around it. Match the surrounding
   code's style, naming and comment density.
2. Before adding or upgrading a dependency, model or tool, check its current version and license online
   (allowed: MIT, Apache-2.0, BSD, ISC, Zlib, OFL, MPL-2.0; CC-BY-4.0 weights with attribution).
3. Write the test first when fixing a bug. Every fix ships a regression test.
4. Run the checks for what you touched (commands in `AGENTS.md`), then `pnpm check` before you finish.
5. Record decisions as ADRs, and flag anything that changes cost, privacy, security or architecture.
6. Update `AGENTS.md` (and the phase doc) when commands, layout, rules or the current phase change.

**Protected core.** The paths in [`protected-core.txt`](../protected-core.txt) are never edited directly, by
any assistant. For a change there:
1. Work in a scratch git worktree.
2. Produce a patch over just those paths.
3. Prove it passes the full suite with the patch applied.
4. Write `docs/proposals/<name>.md` (why, what, how it was tested, how to apply, what to look at) next to
   `<name>.patch`.

The owner applies it. Tests that depend on a not-yet-applied patch must pass both ways (check whether the
protected piece exists and assert the right behaviour for each case), never be skipped to hide a failure.

**Generated files** (`packages/design-tokens/generated/`, `packages/shared-types/src/{api,events}.ts`,
`openapi.json`) come from `pnpm tokens` and `pnpm gen:types`, never hand edits. Change a Python API model,
then regenerate.

## How a phase is delivered

1. **Scope:** exactly SPEC §25 for that phase, nothing from later phases.
2. **Dependencies:** check versions and licenses online, and write an ADR for the phase's design.
3. **Build it** with tests at every level: unit, integration (`tests/integration`), and an Electron e2e test
   for the phase's "done when" (`tests/e2e`).
4. **Protected parts** go in a patch and proposal (above), verified in a scratch worktree.
5. **Write `docs/PHASE-N.md`:**
   - status;
   - the "done when" and its result;
   - what you can do now;
   - setup;
   - a demo script;
   - a tests table with counts;
   - bugs found and fixed;
   - known limitations;
   - what's next.
6. **Update the rest:** `AGENTS.md` (current phase, commands, layout), `README.md` (status, documents table),
   and the ARCHITECTURE "as built" notes.
7. **Stop** and wait for the owner's review. Record the approval in the phase doc's status line and in
   `AGENTS.md` when it comes.

## Environment notes (learned the hard way)

**Installing and running the app**
- **Install:** `uv sync` and `pnpm install`. pnpm 12 (`npm i -g pnpm@12.11.2`), Python 3.12 via uv.
- **Run:** `pnpm dev`. On Linux as root, Electron needs `pnpm dev -- --no-sandbox`. Windows doesn't.
- **Electron e2e:** needs `pnpm build` first. On Linux without a display, use `xvfb-run -a pnpm test:e2e`.

**Tests that need a moment**
- **Real Ollama tests** run when `ollama` is on `PATH` or `UNIVERSE_TEST_OLLAMA` is set; otherwise they're
  skipped. Everything else uses the fake Ollama (`tests/support/fake_ollama.py`, scripted tool calls included).
- **Slow tests:** the Phase 2 done-when test takes about 3 minutes (500 files), and the Phase 4 universe e2e
  seeds 50,000 items. A quiet test run is usually one of these, not a hang.

**Shell and tooling pitfalls**
- **Don't `pkill -f` a pattern** that also matches your own shell's command line; it kills the shell.
- **Scratch worktrees** for protected patches:
  - They need their own `.venv` (`uv sync --frozen`): the main venv's editable installs point at the main
    checkout.
  - They need their own `node_modules` (`pnpm install --frozen-lockfile`): pnpm refuses symlinked ones.
- **Heredocs:** quote them (`<<'EOF'`) when writing TypeScript from a shell. Template literals otherwise get
  expanded.
- **React lint:** the React Compiler lint rules apply. Mutate through refs, and keep component files exporting
  only components (helpers go in `helpers.ts` or `lib/`).

**Hardware and CI**
- **No GPU in CI or cloud sandboxes:** FPS budgets can only be proven on the owner's machine
  (`pnpm bench:universe`).

## Which file each tool reads

Every one of these points to `AGENTS.md`; none has rules of its own.

| Tool | Reads | In this repo |
| --- | --- | --- |
| Codex, Cursor, Windsurf, Amp, Devin, Jules | `AGENTS.md` natively | `AGENTS.md` |
| GitHub Copilot | `AGENTS.md`, plus `.github/copilot-instructions.md` | both (the latter points here) |
| Cline | `AGENTS.md` natively (also `.clinerules/`) | `AGENTS.md` |
| Claude Code | `CLAUDE.md` | `CLAUDE.md` imports `AGENTS.md` with `@AGENTS.md` |
| Gemini CLI | `GEMINI.md`, or the names in `context.fileName` | `.gemini/settings.json` lists `AGENTS.md` |
| Aider | files listed under `read:` in `.aider.conf.yml` | `.aider.conf.yml` reads `AGENTS.md` |
| Anything else | whatever you paste | the [start prompt](#start-prompt) above |

If a tool's version doesn't pick up `AGENTS.md`, add the smallest pointer file it does read, saying "Follow
`AGENTS.md`", and add it to this table and to `tests/unit/test_handoff.py`.

## Handing off at the end of a session

Leave the repository so the next assistant needs nothing but the files:
- Commit and push all work, with clear messages. Nothing important lives only in a chat.
- Update the **Current phase** line in `AGENTS.md`: what's delivered, what's waiting on the owner, what's next.
- Put open problems in the phase doc's known limitations or a proposal's status line, not in your memory.
- If a check is red, say which one and why in the phase doc. Never leave it silently red.
