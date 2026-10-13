# Architecture Decision Records

One file per decision: `NNNN-short-title.md`, numbered in order, never renumbered. A superseded ADR stays in place with `Status: Superseded by NNNN`.

Template:

```markdown
# NNNN — Title

- Status: Proposed | Accepted | Superseded by NNNN
- Date: YYYY-MM-DD
- Flags: cost | privacy | security | architecture (if the decision materially changes one of these)

## Context
## Decision
## Consequences
## Alternatives considered
```

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-process-model-and-supervisor.md) | Electron shell, process model and a stdlib-only supervisor | Accepted |
| [0002](0002-sqlite-job-queue.md) | Custom SQLite job queue instead of huey | Accepted |
| [0003](0003-storage-layout.md) | Storage layout: vault files, three SQLite files, LanceDB, no ORM | Accepted |
| [0004](0004-custom-agent-loop.md) | Custom agent loop instead of PydanticAI | Accepted |
| [0005](0005-model-runtimes.md) | Model runtimes: Ollama + ONNX Runtime models service | Accepted |
| [0006](0006-local-security-model.md) | Local security model: loopback, session token, egress gate, policy engine | Accepted |
| [0007](0007-runtime-pins.md) | Runtime pins: Python 3.12, TypeScript 6.0, Node 24 LTS | Accepted |
| [0008](0008-license-policy.md) | License policy and flagged components | Accepted |
| [0009](0009-electron-privacy-hardening.md) | Electron privacy hardening: no outbound traffic from Chromium | Accepted |
| [0010](0010-phase-2-vault-pipeline.md) | Phase 2 vault pipeline: workers under Core, Ollama embeddings, staged model roles | Accepted |
| [0011](0011-phase-3-agent-engine.md) | Phase 3 agent engine: loop, approvals, protected policy, minimal MCP client | Accepted |
| [0012](0012-phase-4-universe-renderer.md) | Phase 4 universe: scene data, layouts, renderer, Lite mode and viewers | Accepted |
