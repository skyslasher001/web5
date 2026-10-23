# 0001 — Electron shell, process model and a stdlib-only supervisor

- Status: Accepted (2026-10-12)
- Date: 2026-10-12
- Flags: architecture

## Context

SPEC §4 asks for small cooperating processes kept alive by a tiny supervisor, an Electron (or Tauri) shell, and a Python backend. Forge will patch the app's own code (SPEC §9), so whatever restarts and rolls back the app must survive a bad patch or a broken dependency upgrade.

## Decision

- **Shell: Electron 44.** Chromium on every machine gives WebGL/WebGPU parity for the 3D universe, WebRTC echo cancellation for barge-in, `desktopCapturer` for consented screen capture, and mature global shortcuts and tray APIs. DevMind uses the same stack, so its components can be reused.
- **Processes:** Electron main → supervisor → {Core, workers, voice, models service, Ollama, optional sidecars}. Vision runs inside Core (capture happens in Electron, the VLM in Ollama, OCR in the models service).
- **Supervisor = Python 3.12 standard library only.** It runs on the uv-managed base interpreter, *not* the app venv, so no dependency upgrade can break it. It holds children in a Windows Job Object (via `ctypes`) so nothing is orphaned. Its state (releases, last-known-good, boot-failure counter) is a JSON file written atomically, independent of SQLite.
- The supervisor is the **only** component that applies or rolls back code. It's triggered only by Electron main, which holds the supervisor token, after a native approval dialog.
- Electron main restarts the supervisor if it dies. Nothing restarts Electron main (you relaunch it; an optional login item starts it at boot).

## Consequences

- Idle RAM: Electron (~250–400 MB with the scene) + Core (~150 MB) + supervisor (~20 MB). Workers, voice and models start lazily. That fits the 1 GB budget, to be measured in Phase 1.
- Python everywhere on the backend keeps one language for Forge to patch. Only main and the renderer are TypeScript.
- Safe mode needs nothing but Electron main and the supervisor.

## Alternatives considered

- **Tauri 2:** smaller binaries and lower RAM. But WebView2 behaviour differs from Electron's Chromium for capture and audio processing, DevMind reuse is lost, and the RAM saving doesn't matter against the budget.
- **Supervisor in Node (inside Electron main):** fewer processes, but then a renderer or main bug would take the watchdog down with it, and the apply/rollback logic would live in code that is updated more often.
- **Supervisor in Go/Rust:** a robust single binary, but a second toolchain for a ~600-line program.
