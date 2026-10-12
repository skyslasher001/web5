# AGENTS.md — rules for AI coding assistants and Forge

UNIVERSE is a local-first Windows desktop "digital brain": Electron + React UI, Python/FastAPI services, SQLite + LanceDB, local models via Ollama.

## Read first

1. [`SPEC.md`](SPEC.md): the requirements. Every line is a requirement.
2. [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md): the design. Follow it, or change it explicitly with an ADR.
3. [`docs/PHASE-0.md`](docs/PHASE-0.md): current status, open questions, what's next.

**Current phase:** Phase 0 (Blueprint) has been delivered and is **awaiting approval**. Don't start Phase 1 work until the owner approves.

## How to work

- One phase at a time (SPEC §25). A phase ends with runnable code, tests, setup steps, a demo script, known limitations, and what's next.
- Simple over clever. No abstractions beyond the plugin interfaces.
- Verify current versions, models and licenses online before adding or upgrading anything. Don't rely on memory.
- Record decisions as ADRs in `docs/adr/` (template in `docs/adr/README.md`). Flag in 1–2 lines anything that materially changes cost, privacy, security or architecture.
- When something fails, show the real error and fix it. Never paper over failures with mocks.
- Keep this file and `CLAUDE.md` current when commands, layout or rules change.

## Hard rules

- **Protected core — never modify** (from Phase 1 the list lives in `protected-core.txt`, and the supervisor enforces it): the permission/policy engine, consent controls, kill switch, audit log writer, budget caps, Sentinel, the supervisor, the update/rollback mechanism, `agents/forge.yaml`, `agents/sentinel.yaml`, `protected-core.txt`, `tests/protected/`, CI and pre-commit config. For these, write a proposal (diff + explanation) for the owner to apply.
- **Never disable, skip or weaken a test**, loosen an assertion, or lower a threshold to make something pass. Every bug fix ships a regression test.
- **Never delete or rewrite vault data.** Tests use the seed-data generator and temporary vaults, never a real vault path.
- **Licenses:** only MIT / Apache-2.0 / BSD / ISC / Zlib / OFL / MPL-2.0 (plus CC-BY-4.0 weights with attribution). Flag GPL, AGPL or non-commercial items with an alternative before adopting them. See [ADR-0008](docs/adr/0008-license-policy.md).
- **No secrets** in code, config, logs or commits. Use the OS credential store (`keyring`).
- **Outbound network only through the egress gate** (`services/common`, from Phase 1). No direct HTTP clients elsewhere.
- **Consent stays off by default:** mic, screen and camera. Nothing captured is stored unless the owner says so.

## Commands

None yet. Phase 1 adds `pnpm dev` (one-command start), `pnpm test`, `uv run pytest`, and the `pre-commit` hooks.

## Legacy code

`src/`, `index.html`, `vite.config.ts`, `tailwind.config.js` and friends are a pre-existing Bolt landing page that has nothing to do with UNIVERSE. Phase 1 replaces them (pending owner confirmation, PHASE-0.md Question 1). Don't extend them.
