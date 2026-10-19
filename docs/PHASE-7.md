# Phase 7 — Voice

Delivered 2026-10-19. Design: [ADR-0016](adr/0016-phase-7-voice.md). Protected part:
[docs/proposals/phase-7-consent.md](proposals/phase-7-consent.md) (microphone consent, waiting for you).

You can talk to UNIVERSE and it talks back, all on this computer: speech-to-text, a voice for every agent, a
wake phrase, push-to-talk, continuous mode, barge-in, voice navigation, approvals by voice, dictation, and voice
memos that land in the vault already transcribed.

## What exists now

### The voice orb

Bottom center, beside Core's chat orb (alone in zen mode). It shows **idle**, **listening** (a live waveform of
your mic), **thinking** and **speaking**, with what it heard and what it's saying in a bubble above. Next to it:
the **mic** switch, **record a memo**, and **Voice settings**. A red **"Microphone on"** badge sits in the
always-on-top consent layer whenever the mic is open.

### Listening: three modes

- **Push to talk** (default): hold the orb, or hold **Space** (when you're not typing).
- **Wake word**: start with the wake phrase, "Hey Universe, go to Ember Wolf", or say it alone and then the
  command within 6 s. You can change the phrase.
- **Continuous**: every sentence counts; after 30 s of quiet it falls back to wake word.

Say "continuous mode", "wake word mode" or "push to talk" to switch.

**Barge-in:** start talking while it's speaking and it stops at once (the voice process keeps listening while it
speaks; Chromium's echo cancellation keeps its own voice out). Holding push-to-talk interrupts too. "Stop" also
cancels the answer being written.

### What you can say

| You say | What happens |
| --- | --- |
| "Take me to Ember Wolf", "Go to DevMind" | Core's recall fast path (no LLM): the camera flies to the galaxy, Navigator says "Flying to …". |
| "Open the lease", "Play the song I made in March" | The item opens in its viewer ("Here's …"). |
| "Show photos from the lake", "Find the survey" | Results light up in the universe ("I found 4 results. The first is …"). |
| "Open the agents panel", "Show voice settings" | Side panel tabs. |
| "Grid view", "List view", "Universe view", "Zen mode", "Go home", "Zoom in/out", "Go back", "Open/close chat" | Views and navigation. |
| "Read it" | Reads the open item aloud. |
| "Approve" / "Deny" | Answers the oldest waiting approval. Agents' requests are read out ("Core asks to …. Say approve or deny."). High-risk actions and "remember this" rules need a click: Core refuses them by voice. |
| "Take a memo" … "Save the memo" | Records a voice memo; saving stores it in the vault (minus the "save the memo" at the end) and the pipeline transcribes it. "Discard the memo" drops it. |
| "Start dictation" … "Stop dictation" | What you say is typed into the focused text field (any editor in the app). |
| "Stop", "Never mind" | Stops speaking. |
| "Turn off the mic", "Kill switch" | What it says. |
| Anything else ("What did I decide about the bridge?", "Forge, what broke?") | Goes to Core. The answer streams back and is **spoken sentence by sentence** as it's written, in the voice of whichever agent answers. |

### Voices

Kokoro-82M, 28 English voices. Each agent has its own: Core `af_heart`, Navigator `af_nova`, Librarian
`bf_emma`, Scribe `am_michael`, Critic `bm_george`, Researcher `am_puck`, Forge `am_onyx`, Sentinel `bm_lewis`
(agent YAMLs name a character, Core maps it). Change any of them, and the speed, in **Voice → Voices**; the play
button says hello in that voice.

### Memos and transcription in the vault

The vault's `transcribe` stage is real now. Every **audio, song, voice memo and video** item is decoded,
split into stretches of speech by the VAD (at most 28 s each), and transcribed; each piece becomes a searchable
text chunk with **start/end timestamps**, mirrored into the item's sidecar as `transcript`. WAV needs nothing
else; MP3, M4A, video and the rest need an `ffmpeg` executable on PATH (run as a separate program). Without it,
or without a Whisper model, the stage is skipped with that reason; **installing a Whisper model requeues those
items** automatically. Recordings longer than 3 hours are skipped.

### Under the hood

- `services/voice` (`universe_voice`): the voice process. Audio helpers, Whisper's log-mel front end, Whisper
  ONNX with a greedy decoder, Silero VAD (or an energy VAD) and an endpointer, Kokoro with our own
  grapheme-to-phoneme (misaki's lexicons, numbers, acronyms), the transcript wake phrase, the session state
  machine (modes, barge-in), single-use HMAC tickets, the model catalog with pinned SHA-256s, long-recording
  transcription, and a Starlette WebSocket server.
- Core: `voice_runtime.py` runs the voice process only while voice is on (port file handshake, health checks,
  restart with backoff, stops on the kill switch) and installs models through the egress gate; `voice_api.py`
  has `GET /voice/status`, `POST /voice/start|stop`, `PUT /voice/settings`, `GET /voices`,
  `POST /voice/models/{id}/install`, `POST /voice/memo`, and **`WS /ws/voice`**, which relays audio between the
  renderer and the voice process (the renderer's CSP still only allows Core).
- Renderer: `lib/voiceClient.ts` (16 kHz AudioWorklet capture with echo cancellation, PCM16 over the socket, a
  gap-free 24 kHz playback queue, memos), `lib/voice.ts` (what each sentence does), `lib/voiceCommands.ts` (the
  grammar), `hud/VoiceOrb.tsx`, `hud/VoicePanel.tsx`.

## Setup

1. `uv sync` (adds `misaki` for its lexicons and `websockets` for the voice server; no PyTorch, no FFmpeg).
2. Open **Voice** in the side panel and **Install** Whisper tiny.en (118 MB), Kokoro (121 MB) and Silero VAD
   (2 MB). They download from GitHub releases through the egress gate (blocked while offline or under the kill
   switch, logged in the audit) and are checked against pinned SHA-256s; a mismatch installs nothing. They land in
   `<data dir>/models/voice/`. Whisper base.en (209 MB) is optional: more accurate, about twice as slow (it's
   preferred for vault transcription when installed).
3. **Apply the consent patch** so the microphone can open:
   `git apply docs/proposals/phase-7-consent.patch` (see the proposal). Until then voice speaks but can't listen.
4. Optional: put `ffmpeg` on PATH to transcribe MP3, M4A and video in the vault.
5. Turn the mic on with the orb's mic button. A native dialog asks once per launch.

## Demo script

1. **Voice → Turn on.** The orb goes from grey to idle. Press play next to Navigator: "Hi, I'm Navigator."
2. Click the **mic** button, confirm the native dialog. The red "Microphone on" badge appears (and the tray
   tooltip says so).
3. Hold **Space**: "Take me to Ember Wolf." The camera flies there; Navigator says "Flying to Ember Wolf
   Acquisitions." The Voice panel shows the latency of that answer.
4. Say "continuous mode". From now on, no keys: "Open the lease." "Read it." "Show photos from the lake."
   "Grid view." "Go home."
5. Ask "What did I decide about the bridge?" and interrupt it mid-sentence with "Stop": it stops at once.
6. "Take a memo." Talk for a while. "Save the memo." Find it in the Vault: it's a voice memo with its
   transcript; search for a word you said.
7. Ask Core to do something that needs approval ("link my land-deal notes to DevMind"): it reads the request out;
   say "Approve."
8. Press the kill switch: the mic closes at once, the page reloads, voice stops.

## Done-when

> *"I can run the app for 10 minutes by voice alone."*

Everything in the table above is reachable by voice; the only clicks are turning the mic on (consent: on purpose,
once per launch) and high-risk approvals (on purpose). What CI verifies, without a microphone or models:

```sh
uv run pytest tests/unit/test_voice.py tests/integration/test_voice.py tests/integration/test_vault_pipeline.py
pnpm exec vitest run apps/ui/src/lib/voiceCommands.test.ts apps/ui/src/lib/voiceClient.test.ts
pnpm build && xvfb-run -a pnpm exec playwright test tests/e2e/app.spec.ts -g "Phase 7"
```

- the voice package: endpointing, modes, wake phrase, barge-in, numbers and phonemes, tickets, hash-checked
  installs, long-recording segmentation (34 tests);
- Core: the real voice process started and stopped, speaking and listening through `/ws/voice`, single-use
  tickets, settings and per-agent voices, the kill switch stopping voice, a memo saved and transcribed, installs
  that follow redirects, refuse a bad hash, requeue transcription and are blocked offline;
- approvals by voice are recorded as `voice` and refused for high risk and standing rules;
- the e2e: voice turns on in the real app, commands, navigation (the camera flies to Ember Wolf) and a question
  routed and answered; the mic stays off without the patch, and with it (a fake mic) opens only after the
  native dialog and closes on the kill switch.

With the real models (`UNIVERSE_TEST_VOICE_MODELS=<data dir>/models/voice`), `tests/integration/test_voice_models.py`
also runs: Kokoro speaks SPEC's own commands, Silero finds them, Whisper writes them down word for word; the wake
phrase; a memo transcribed with timestamps; and the speed of each step.

The 10-minute session itself needs a microphone and your voice: run the demo script after applying the patch.

## Measured

On the 4-core Linux build machine, **CPU only** (no GPU; on yours ONNX Runtime uses CUDA or DirectML when it
can), with the real models:

| Step | Time |
| --- | --- |
| Whisper tiny.en, a 2.5 s command | 435 ms median (max 455) |
| Whisper base.en, the same | 740 ms median (max 964) |
| Kokoro, the first spoken sentence | 646 ms median (max 961) |
| Silero VAD | 8 ms per second of audio |
| Silence before a hands-free sentence counts as finished | 700 ms (the endpointer's hang-over) |

So, from your last word to the first word back, for a navigation command (no LLM): **about 1.2 s with
push-to-talk** (release → Whisper → recall → Kokoro), within the 1.5 s budget; **about 1.8 s hands-free** (wake
or continuous), because of the 0.7 s of silence it waits for. A question to Core adds the model's time to its first
sentence. The Voice panel measures every answer from your actual last word, that silence included.

## Known limitations

- **The mic needs the consent patch** (protected core). Without it voice speaks but doesn't listen.
- **Echo cancellation is Chromium's.** If your speakers are loud and your mic close, its own voice can trigger
  barge-in; a headset avoids it. To verify on your hardware.
- **Whisper tiny.en** mishears rare names now and then ("Prin" for "Prynne"); base.en is better and slower.
  Names in your vault aren't yet given to Whisper as hints.
- **The wake phrase is transcript-based:** each utterance in wake mode costs a short Whisper run, and a
  similar-sounding phrase can wake it. A dedicated wake-word model (livekit-wakeword, Apache-2.0) can replace it.
- **Our grapheme-to-phoneme is simpler than misaki's full pipeline:** words outside its 183k-word lexicon are
  pronounced by rules and can sound off. English only (your decision).
- **Hands-free misses the 1.5 s budget on a CPU-only machine** (about 1.8 s here: 0.7 s of silence detection plus
  Whisper plus Kokoro); push-to-talk meets it (about 1.2 s). A GPU, a shorter hang-over, or speaking a short
  acknowledgement first would close the gap; to measure on your hardware first. A question's first spoken
  sentence also waits for the chat model's first sentence. The Voice panel measures every answer.
- **Transcribing MP3, M4A and video** needs `ffmpeg` on PATH; WAV works without it.
- **No partial transcripts** while you talk (the orb shows the waveform; the text appears when you stop).

## What's next

Phase 8 per SPEC §25: **Vision** (consented screen, window and region capture, "look at this", watch mode,
camera toggle). It reuses this phase's consent design in Electron main for screen and camera.
