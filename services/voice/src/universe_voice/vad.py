"""Voice activity detection and endpointing (ADR-0016).

`SileroVAD` runs the Silero VAD ONNX model (MIT) on 32 ms frames, carrying its recurrent state and a 64-sample
context between calls the way the reference implementation does. `EnergyVAD` is a model-free fallback (and
what the unit tests use). `Endpointer` turns per-frame speech probabilities into utterances: it keeps a short
pre-roll so the first syllable isn't clipped, waits out a silence hangover before calling the end, and caps an
utterance at 30 s (one Whisper window).
"""

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

import numpy as np

from universe_voice.audio import STT_RATE, Audio

FRAME = 512  # samples per VAD frame at 16 kHz (32 ms)
FRAME_S = FRAME / STT_RATE


class VAD(Protocol):
    def prob(self, frame: Audio) -> float: ...

    def reset(self) -> None: ...


class SileroVAD:
    CONTEXT = 64

    def __init__(self, model_path: Path) -> None:
        from universe_voice.stt import session

        self._session = session(model_path, threads=1)
        self.reset()

    def reset(self) -> None:
        self._state = np.zeros((2, 1, 128), dtype=np.float32)
        self._context = np.zeros((1, self.CONTEXT), dtype=np.float32)

    def prob(self, frame: Audio) -> float:
        x = np.concatenate([self._context, frame.reshape(1, -1).astype(np.float32)], axis=1)
        out, state = self._session.run(
            None, {"input": x, "state": self._state, "sr": np.array(STT_RATE, dtype=np.int64)}
        )
        self._state = np.asarray(state, dtype=np.float32)
        self._context = x[:, -self.CONTEXT :]
        return float(np.asarray(out).ravel()[0])


class EnergyVAD:
    """Loudness against a slowly adapting noise floor. Crude, but needs no model."""

    def __init__(self, ratio: float = 3.0, floor: float = 0.003) -> None:
        self.ratio, self.min_floor = ratio, floor
        self.reset()

    def reset(self) -> None:
        self._noise = self.min_floor

    def prob(self, frame: Audio) -> float:
        rms = float(np.sqrt(np.mean(np.square(frame, dtype=np.float64)))) if frame.size else 0.0
        speech = rms > max(self._noise, self.min_floor) * self.ratio
        if not speech:  # learn the floor only from non-speech
            self._noise = 0.95 * self._noise + 0.05 * max(rms, self.min_floor)
        return 1.0 if speech else 0.0


@dataclass
class Segment:
    """What the endpointer reports for each frame fed to it."""

    started: bool = False  # speech just began (barge-in uses this)
    ended: Audio | None = None  # a finished utterance, pre-roll included


@dataclass
class Endpointer:
    vad: VAD
    threshold: float = 0.5
    min_speech_s: float = 0.25
    hangover_s: float = 0.7  # silence that ends an utterance
    preroll_s: float = 0.3
    max_s: float = 30.0
    _pre: deque[Audio] = field(default_factory=deque)
    _speech: list[Audio] = field(default_factory=list)
    _voiced: int = 0
    _silent: int = 0
    _buffer: Audio = field(default_factory=lambda: np.zeros(0, dtype=np.float32))

    @property
    def in_speech(self) -> bool:
        return bool(self._speech)

    def reset(self) -> None:
        self.vad.reset()
        self._pre.clear()
        self._speech, self._voiced, self._silent = [], 0, 0
        self._buffer = np.zeros(0, dtype=np.float32)

    def feed(self, audio: Audio) -> list[Segment]:
        """Feed any amount of 16 kHz audio; returns one event per completed 512-sample frame that changed state."""
        self._buffer = np.concatenate([self._buffer, audio.astype(np.float32)])
        events = []
        while self._buffer.size >= FRAME:
            frame, self._buffer = self._buffer[:FRAME], self._buffer[FRAME:]
            event = self._frame(frame)
            if event.started or event.ended is not None:
                events.append(event)
        return events

    def flush(self) -> Audio | None:
        """End the current utterance now (push-to-talk released)."""
        if not self._speech:
            return None
        utterance = np.concatenate(self._speech)
        self._speech, self._voiced, self._silent = [], 0, 0
        return utterance if self._voiced_enough(utterance) else None

    def _voiced_enough(self, utterance: Audio) -> bool:
        return utterance.size >= int((self.min_speech_s + self.preroll_s) * STT_RATE) * 0.6

    def _frame(self, frame: Audio) -> Segment:
        speaking = self.vad.prob(frame) >= self.threshold
        if not self._speech:
            self._pre.append(frame)
            while len(self._pre) * FRAME_S > self.preroll_s:
                self._pre.popleft()
            if not speaking:
                self._voiced = 0
                return Segment()
            self._voiced += 1
            if self._voiced * FRAME_S < self.min_speech_s:
                return Segment()
            self._speech = list(self._pre)
            self._pre.clear()
            self._silent = 0
            return Segment(started=True)
        self._speech.append(frame)
        self._silent = 0 if speaking else self._silent + 1
        too_long = len(self._speech) * FRAME_S >= self.max_s
        if self._silent * FRAME_S >= self.hangover_s or too_long:
            utterance = np.concatenate(self._speech)
            self._speech, self._voiced, self._silent = [], 0, 0
            return Segment(ended=utterance)
        return Segment()
