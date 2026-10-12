# 0005 — Model runtimes: Ollama + ONNX Runtime models service

- Status: Proposed
- Date: 2026-10-12
- Flags: cost, architecture

## Context

SPEC §15: local-first, $0 by default, providers behind one OpenAI-compatible interface, hardware-aware loadouts, a Model Manager, and no hardcoded model choices.

## Decision

- **Ollama** (MIT) is the primary runtime for LLMs, VLMs and text embeddings. It's native on Windows, detects GPUs, pulls models, keeps them resident (`keep_alive`) and is OpenAI-compatible. Supervised, bound to 127.0.0.1.
- **llama.cpp `llama-server`** (MIT) is an alternative LLM plugin for finer control (e.g. MoE expert offload on 12–16 GB GPUs).
- **Models service** (Python + ONNX Runtime 1.31: CUDA EP on NVIDIA, DirectML EP on AMD/Intel, CPU fallback) hosts the rerankers, SigLIP image/text encoders and RapidOCR. It also runs hardware detection.
- The **voice service** hosts STT (faster-whisper / CTranslate2), VAD, wake word and TTS (Kokoro ONNX), so realtime audio never queues behind other inference.
- **Model broker** (in Core): one priority queue in front of every inference call, with per-class concurrency, so background work never starves voice or chat.
- **Cloud:** off. It's an opt-in OpenAI-compatible provider per agent, behind hard monthly and per-agent caps enforced before each call. The key lives in Credential Manager.
- The model shortlist per hardware tier is in ARCHITECTURE.md §2.3. Final assignments come from Phase 1 hardware detection plus local benchmarks.

## Consequences

- Two inference runtimes to supervise (Ollama + ONNX Runtime), plus CTranslate2 inside voice.
- The VRAM manager must account for all three. Phase 1 measures resident sizes per loadout.

## Alternatives considered

- **Everything in Ollama:** Ollama doesn't serve rerankers, SigLIP or OCR models.
- **PyTorch / sentence-transformers in-process:** simpler code, but adds GBs of install size and slower cold starts. ONNX exports exist for every shortlisted model.
