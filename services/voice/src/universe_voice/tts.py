"""Text to speech: Kokoro-82M on ONNX Runtime (ADR-0016).

Weights and voices are Apache-2.0 (hexgrad/Kokoro-82M, as exported in thewh1teagle/kokoro-onnx's releases).
Phonemes come from our own G2P (`g2p.py`), not espeak-ng. The model takes phoneme ids padded with 0 at both
ends, a 256-wide style vector picked from the voice by phoneme count, and a speed; it returns 24 kHz audio.
Text is spoken sentence by sentence so the first audio is ready quickly and barge-in can stop between pieces.
"""

import json
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Protocol

import numpy as np

from universe_voice.audio import TTS_RATE, Audio
from universe_voice.g2p import phonemize

MAX_PHONEMES = 510
_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")


class TTS(Protocol):
    name: str
    rate: int

    def voices(self) -> list[str]: ...

    def speak(self, text: str, voice: str, speed: float = 1.0) -> Iterator[Audio]: ...


@cache
def vocab() -> dict[str, int]:
    """Kokoro's phoneme → id table (from the model's config.json, Apache-2.0)."""
    return json.loads(resources.files("universe_voice").joinpath("kokoro_vocab.json").read_text(encoding="utf-8"))


def tokens(phonemes: str) -> list[int]:
    table = vocab()
    return [table[p] for p in phonemes if p in table]


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text.strip()) if s.strip()]


def _chunks(ids: list[int], space: int) -> list[list[int]]:
    """Split a long sentence at word boundaries so no piece exceeds the model's 510-phoneme window."""
    out: list[list[int]] = []
    while len(ids) > MAX_PHONEMES:
        cut = max((i for i in range(MAX_PHONEMES) if ids[i] == space), default=MAX_PHONEMES)
        out.append(ids[:cut])
        ids = ids[cut + 1 :] if cut < MAX_PHONEMES else ids[cut:]
    if ids:
        out.append(ids)
    return out


@dataclass
class Spoken:
    phonemes: int
    seconds: float


class KokoroTTS:
    rate = TTS_RATE

    def __init__(self, model_path: Path, voices_path: Path, threads: int = 0) -> None:
        from universe_voice.stt import session

        self.name = f"kokoro:{model_path.stem}"
        self._session = session(model_path, threads)
        self._inputs = {i.name for i in self._session.get_inputs()}
        with np.load(voices_path) as data:
            self._voices = {name: np.asarray(data[name], dtype=np.float32) for name in data.files}
        self.last = Spoken(0, 0.0)

    def voices(self) -> list[str]:
        return sorted(self._voices)

    def _infer(self, ids: list[int], style: np.ndarray, speed: float) -> Audio:
        name = "input_ids" if "input_ids" in self._inputs else "tokens"
        row = style[min(len(ids), len(style)) - 1].reshape(1, -1)
        (audio,) = self._session.run(
            None,
            {
                name: np.array([[0, *ids, 0]], dtype=np.int64),
                "style": row.astype(np.float32),
                "speed": np.array([speed], dtype=np.float32),
            },
        )
        return np.asarray(audio, dtype=np.float32).ravel()

    def speak(self, text: str, voice: str, speed: float = 1.0) -> Iterator[Audio]:
        if voice not in self._voices:
            raise ValueError(f"unknown voice {voice!r}")
        if not 0.5 <= speed <= 2.0:
            raise ValueError("speed must be between 0.5 and 2.0")
        style, space = self._voices[voice], vocab()[" "]
        for sentence in sentences(text):
            ids = tokens(phonemize(sentence))
            for piece in _chunks(ids, space):
                started = time.perf_counter()
                audio = self._infer(piece, style, speed)
                self.last = Spoken(len(piece), time.perf_counter() - started)
                yield audio
