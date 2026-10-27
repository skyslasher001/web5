# 0016 — Phase 7: Voice (an ONNX-only local stack, Core-run voice process, consent in main)

- Status: Accepted (built 2026-10-19)
- Date: 2026-10-19
- Flags: privacy, security, architecture

## Context

SPEC §11 and §25 Phase 7: speech-to-text, text-to-speech, a wake word, push-to-talk, continuous mode, barge-in,
a voice per agent and full voice navigation; dictation into any editor; voice memos transcribed into the vault
automatically; a voice orb (idle, listening with a waveform, thinking, speaking); under 1.5 s from the end of
your sentence to the first spoken word. **Done when:** *"I can run the app for 10 minutes by voice alone."*
Owner decisions in force: English only, no cloud LLM, consent off by default.

ARCHITECTURE §2 named faster-whisper, Kokoro via kokoro-onnx, Silero VAD and openWakeWord, "or the current best
open equivalent". Checking each against ADR-0008 (licenses) before adopting it changed most of that list:

- **faster-whisper** depends on PyAV, whose wheels bundle LGPL FFmpeg loaded in-process. ADR-0008 allows
  copyleft only unmodified in a separate process.
- **kokoro-onnx** depends on `espeakng-loader` (GPL espeak-ng, in-process) and `phonemizer` (GPL-3.0).
  **misaki[en]** (Kokoro's own G2P) pulls in `num2words` (LGPL) and spaCy.
- **openWakeWord**'s code is Apache-2.0, but its pretrained wake-word models are CC BY-NC-SA (non-commercial).
- **Piper** TTS is MIT, but its maintained fork is GPL.
- Hugging Face is unreachable from the build sandbox; GitHub release assets are reachable. That is where every
  model below is fetched from, pinned by size and SHA-256.

## Decision

**1. One runtime for everything: ONNX Runtime** (MIT, already a dependency for OCR) plus numpy. No PyTorch, no
FFmpeg in-process, no espeak.

| Part | What | License |
| --- | --- | --- |
| STT | OpenAI **Whisper** tiny.en (default, ~0.25× real time on a CPU) or base.en, ONNX export by k2-fsa/sherpa-onnx (int8). Our own log-mel front end (numpy, matches Whisper's) and greedy decoder with Whisper's token suppression and a repetition guard. | MIT weights, Apache-2.0 export |
| TTS | **Kokoro-82M** int8 ONNX with its 54 voices (28 English used). Our own grapheme-to-phoneme over misaki's US gold + silver lexicons (183k words; misaki 0.9.4 is a lexicon-only dependency here), with suffix rules, number reading and acronym spelling. | Apache-2.0 |
| VAD | **Silero VAD** ONNX (pinned by hash), streaming (512-sample frames with 64 samples of context and carried state); an energy VAD when it isn't installed. | MIT |
| Wake word | **Transcript-based**: the VAD finds an utterance, Whisper transcribes it, and a fuzzy prefix match finds the wake phrase ("Hey Universe" by default; you can change it). Costs one short STT run per utterance, needs no extra model, and works for any phrase. | — |
| Decoding other formats (vault transcription) | An `ffmpeg` **executable** on PATH, run as a separate process; WAV needs nothing. | LGPL/GPL binary, separate process (ADR-0008) |

**2. A voice process run by Core** (`python -m universe_voice`), like the pipeline workers (ADR-0010), not by the
supervisor as ARCHITECTURE §1 planned. It starts when you turn voice on and stops when you turn it off or the
kill switch engages, so no models sit in memory otherwise. Core gives it a per-boot key, it binds any free
loopback port and writes it to a file, Core health-checks it and restarts it with backoff. A crash costs only
voice.

**3. One audio socket, through Core.** The renderer opens `WS /ws/voice` on Core with an ordinary single-use
session ticket; Core relays frames to the voice process, which only accepts Core (an HMAC-signed single-use
ticket). The renderer's CSP keeps allowing only Core, and the voice port stays private. Up: 16 kHz PCM16 and
JSON controls (`mode`, `push`, `speak`, `stop`, `playing`). Down: events (`state`, `level`, `final`, `wake`,
`barge_in`, `timeout`…) and speech as 24 kHz PCM16 per sentence.

**4. Capture and playback in the renderer** (as ARCHITECTURE §1.2 planned): an AudioWorklet at 16 kHz with
Chromium's echo cancellation, noise suppression and gain control; a gap-free playback queue. Barge-in: the voice
process keeps listening while it speaks and says `barge_in` the moment speech starts during playback.

**5. Latency by streaming.** Core's chat reply is spoken sentence by sentence as the tokens arrive, so the
first sentence is synthesised while the model is still writing. Navigation never touches an LLM: "go to /
open / show …" takes the existing `POST /recall` fast path. The Voice panel shows the measured latency of the
last answer.

**6. Consent belongs to Electron main** (protected core; `docs/proposals/phase-7-consent.md`). Main alone lets
Chromium open an audio-only stream for our own main window, only after you confirm a native dialog (once per
launch); the mic is off at every launch; the kill switch revokes it first and reloads the page holding the
stream; main reports every change to Core's protected consent record (audit + `consent.changed`). Until the
patch is applied the bridge answers "needs the Phase 7 patch" and the mic cannot open; voice can still speak.

**7. Nothing is stored** except a memo you record and save: it becomes a `voice_memo` item, and the vault's new
`transcribe` stage turns every audio and video item into timestamped text chunks (VAD-segmented, ≤ 28 s each),
mirrored into the sidecar. Installing a Whisper model requeues items that were skipped for lack of one.

**8. Per-agent voices.** Agent YAMLs name a voice by character (`calm-neutral`, `bright-guide`…), mapped to
Kokoro voices in Core; you can override any agent in the Voice panel. Forge and Sentinel (protected YAMLs) get
theirs from a code fallback.

## Consequences

- No new copyleft, no PyTorch, ~250 MB of optional models, all downloaded through the egress gate (offline and
  the kill switch block it; the audit log records each request, redirects included), hash-checked, fail closed.
- Whisper tiny.en is less accurate than larger models; base.en is one click away (and preferred for vault
  transcription, where speed matters less).
- Our G2P is simpler than misaki's full pipeline: rare words fall back to letter rules. English only, as decided.
- The transcript wake word costs a short Whisper run per utterance in wake mode (~0.1–0.3 s CPU each) and can
  wake on a similar-sounding phrase; a dedicated wake model (livekit-wakeword, Apache-2.0) can replace it later.
- Echo cancellation relies on Chromium's AEC; on hardware where it fails to cancel our own speech, a headset
  avoids self-interruption.
- Mic access needs the owner's protected-core patch; the app makes that visible everywhere the mic is offered.

## Alternatives considered

- **faster-whisper / CTranslate2**: fastest CPU Whisper, but PyAV's in-process LGPL FFmpeg breaks ADR-0008.
- **whisper.cpp / sherpa-onnx Python wheels**: good, but native extensions we'd pin per platform; plain ONNX
  Runtime is already shipped and tested on Windows.
- **kokoro-onnx + espeak-ng**: best G2P coverage, GPL in-process.
- **Piper**: lighter voices, but the maintained fork is GPL and quality is lower than Kokoro.
- **openWakeWord**: the pretrained models are non-commercial.
- **Voice as a supervisor service** (ARCHITECTURE §1): the supervisor is stdlib-only and protected; Core already
  runs child processes and owns the tickets and the kill switch hook.
- **The renderer connecting straight to the voice port**: would need the CSP widened to any loopback port.
