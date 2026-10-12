# 0008 — License policy and flagged components

- Status: Accepted (2026-10-12)
- Date: 2026-10-12
- Flags: architecture (legal)

## Context

SPEC §3.2: prefer MIT, Apache-2.0, BSD and ISC, and flag GPL, AGPL and non-commercial licenses (code, weights, voices) with an alternative.

## Decision

- Treat UNIVERSE as **distributable** even while it is personal: ship only MIT / Apache-2.0 / BSD / ISC / Zlib / OFL / MPL-2.0 code and weights, plus CC-BY-4.0 weights with attribution.
- Copyleft software may run only **unmodified as a separate process or container** (SearXNG AGPL, LGPL FFmpeg builds). Never link GPL code. Never ship non-commercial weights.
- Every model in the Model Manager shows its license, and non-allowlisted licenses need an explicit per-model opt-in.
- Sentinel checks every new dependency against the allowlist (pip-licenses / license-checker in CI), and Forge proposals that add a non-allowlisted license are rejected.
- The current flags and their alternatives are listed in ARCHITECTURE.md §2.2 (espeak-ng, Piper fork, openWakeWord pretrained models and training data, SearXNG, FFmpeg, pillow-heif, mutagen, PyMuPDF, docling weights, Gemma ≤ 3 terms, Llama license, Docker Desktop).

## Consequences

- A few choices trade quality for license hygiene (espeak fallback disabled in Kokoro; tinytag instead of mutagen).
- An About → Licenses screen is generated from lockfiles and model metadata (Phase 12).

## Alternatives considered

- **Personal-use-only policy** (allow GPL/NC freely): simpler now, but it would force a re-platforming the day anything is shared or sold.
