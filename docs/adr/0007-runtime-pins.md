# 0007 — Runtime pins: Python 3.12, TypeScript 6.0, Node 24 LTS

- Status: Accepted (2026-10-12)
- Date: 2026-10-12
- Flags: none

## Context

SPEC §26.6: verify current versions at build time. Checked against PyPI and npm on 2026-10-12.

## Decision

- **Python 3.12** (uv-managed). `kokoro` 0.9.4 and `misaki` 0.9.4 declare `requires_python <3.13`. CTranslate2 4.8, ONNX Runtime 1.31, LanceDB 0.40 (abi3) and PyTorch 2.14 all ship cp312 Windows wheels.
- **TypeScript 6.0.x.** TypeScript 7.0.2 (native compiler) is `latest`, but `typescript-eslint` 8.71 declares `typescript >=4.8.4 <6.1.0`. Move to TS 7 when the lint tooling supports it.
- **Node 24 LTS** ("Krypton") for tooling. Node 26 is current but not yet LTS. Electron 44 bundles its own Node at runtime.
- **pnpm 12, uv 0.13, Vite 8, React 19.3, Electron 44**, locked in lockfiles in Phase 1.

## Consequences

- Revisit the Python pin when Kokoro supports 3.13+ (Forge's dependency loop will surface it).
- Revisit TypeScript when typescript-eslint supports 7.x.

## Alternatives considered

- **Python 3.13/3.14:** blocked by Kokoro. Kokoro could run in a separate interpreter inside the voice service, but that adds complexity for no user benefit.
