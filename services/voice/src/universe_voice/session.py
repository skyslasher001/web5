"""One voice conversation: frames in, events out (SPEC §11, ADR-0016).

Modes:
- `push_to_talk` — audio counts only while the hotkey is held; releasing it transcribes what was said.
- `wake` — the endpointer listens continuously; an utterance that starts with the wake phrase is a command
  (or, if the phrase stood alone, the next utterance within a few seconds is).
- `continuous` — every utterance is a command until nobody speaks for `continuous_timeout_s`, then it falls
  back to wake mode.

Barge-in: when speech starts while the renderer is playing a spoken answer, the session emits `barge_in` so the
renderer cuts playback at once. Chromium's echo cancellation keeps our own voice from triggering it.

Audio is never stored here. Utterances live in memory only until they're transcribed.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np

from universe_voice.audio import STT_RATE, Audio, level
from universe_voice.stt import STT
from universe_voice.vad import Endpointer
from universe_voice.wake import TranscriptWake

Mode = Literal["push_to_talk", "wake", "continuous"]
MODES: tuple[Mode, ...] = ("push_to_talk", "wake", "continuous")
Event = dict[str, Any]

LEVEL_EVERY_S = 0.1
ARMED_S = 6.0  # after a bare "Hey Universe", how long the next utterance counts as the command
MIN_PTT_S = 0.25


@dataclass
class VoiceSession:
    stt: STT
    endpointer: Endpointer
    emit: Callable[[Event], None]
    mode: Mode = "push_to_talk"
    wake: TranscriptWake = field(default_factory=TranscriptWake)
    continuous_timeout_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    playing: bool = False  # the renderer is speaking an answer
    _held: bool = False
    _ptt: list[Audio] = field(default_factory=list)
    _ptt_samples: int = 0
    _armed_until: float = 0.0
    _last_speech: float = 0.0
    _since_level: float = 0.0

    def __post_init__(self) -> None:
        self._last_speech = self.clock()

    # ---------- controls from the renderer ----------

    def set_mode(self, mode: Mode) -> None:
        if mode not in MODES:
            raise ValueError(f"unknown mode {mode!r}")
        self.mode = mode
        self._held, self._ptt = False, []
        self.endpointer.reset()
        self._last_speech = self.clock()
        self.emit({"type": "mode", "mode": mode})

    def push(self, down: bool) -> None:
        if self.mode != "push_to_talk":
            return
        if down:  # a fresh press, even if a key-up was lost (focus left the window while you held it)
            self._held, self._ptt, self._ptt_samples = True, [], 0
            self._interrupt()
            self.emit({"type": "state", "state": "listening"})
        elif self._held:
            self._release()

    def _release(self) -> None:
        self._held = False
        audio = np.concatenate(self._ptt) if self._ptt else np.zeros(0, dtype=np.float32)
        self._ptt, self._ptt_samples = [], 0
        if audio.size >= MIN_PTT_S * STT_RATE:
            self._transcribe(audio, wake_needed=False)
        else:
            self.emit({"type": "state", "state": "idle"})

    def set_playing(self, playing: bool) -> None:
        self.playing = playing

    # ---------- audio ----------

    def feed(self, audio: Audio) -> None:
        self._since_level += audio.size / STT_RATE
        if self._since_level >= LEVEL_EVERY_S:
            self._since_level = 0.0
            self.emit({"type": "level", "value": round(level(audio), 3)})
        if self.mode == "push_to_talk":
            if self._held:
                room = int(self.endpointer.max_s * STT_RATE) - self._ptt_samples
                self._ptt.append(audio[:room])
                self._ptt_samples += min(room, audio.size)
                if self._ptt_samples >= self.endpointer.max_s * STT_RATE:  # held too long: let go for you
                    self._release()
            return
        for event in self.endpointer.feed(audio):
            if event.started:
                self._last_speech = self.clock()
                self._interrupt()
                self.emit({"type": "state", "state": "listening"})
            if event.ended is not None:
                self._last_speech = self.clock()
                armed = self.clock() < self._armed_until
                # The endpointer knew you'd stopped only after `hangover_s` of silence: that wait counts too.
                waited = self.endpointer.hangover_s
                self._transcribe(event.ended, wake_needed=self.mode == "wake" and not armed, waited_s=waited)
        if (
            self.mode == "continuous"
            and not self.endpointer.in_speech
            and self.clock() - self._last_speech > self.continuous_timeout_s
        ):
            self.emit({"type": "timeout"})
            self.set_mode("wake")

    # ---------- internals ----------

    def _interrupt(self) -> None:
        if self.playing:
            self.playing = False
            self.emit({"type": "barge_in"})

    def _transcribe(self, audio: Audio, *, wake_needed: bool, waited_s: float = 0.0) -> None:
        self.emit({"type": "state", "state": "thinking"})
        result = self.stt.transcribe(audio)
        text = result.text.strip()
        timing = {
            "stt_s": round(result.seconds, 3),
            "audio_s": round(audio.size / STT_RATE, 2),
            "waited_s": round(waited_s, 2),  # silence before the end of speech was known (0 for push-to-talk)
        }
        if not text:
            self.emit({"type": "state", "state": "idle"})
            return
        if wake_needed:
            match = self.wake.match(text)
            if match is None:
                self.emit({"type": "ignored", "text": text})
                self.emit({"type": "state", "state": "idle"})
                return
            if not match.command:  # "Hey Universe" on its own: the next utterance is the command
                self._armed_until = self.clock() + ARMED_S
                self.emit({"type": "wake"})
                self.emit({"type": "state", "state": "listening"})
                return
            text = match.command
        self._armed_until = 0.0
        self.emit({"type": "final", "text": text, **timing})
