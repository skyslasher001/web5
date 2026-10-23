"""Stand-ins for the voice models, which CI can't download (Whisper, Kokoro, Silero: ~250 MB from GitHub).

`FakeSTT` "hears" the next scripted line for every utterance it's given; `FakeTTS` "speaks" a short tone per
sentence. Everything around them (decoding, VAD, endpointing, the session state machine, the WebSocket, the
vault stage) is the real code. With `UNIVERSE_TEST_VOICE_MODELS` pointing at installed models, the real-model
tests run as well.
"""

import time
from collections.abc import Iterator
from dataclasses import dataclass, field

import numpy as np

from universe_voice.audio import STT_RATE, TTS_RATE, Audio
from universe_voice.stt import Transcript
from universe_voice.tts import sentences


@dataclass
class FakeSTT:
    lines: list[str] = field(default_factory=list)
    name: str = "fake-whisper"
    heard: list[float] = field(default_factory=list)  # seconds of audio per call

    def transcribe(self, audio: Audio) -> Transcript:
        self.heard.append(audio.size / STT_RATE)
        return Transcript(self.lines.pop(0) if self.lines else "", 0.01)


@dataclass
class FakeTTS:
    name: str = "fake-kokoro"
    rate: int = TTS_RATE
    delay_s: float = 0.0  # per sentence, to give a barge-in time to land
    spoken: list[tuple[str, str]] = field(default_factory=list)

    def voices(self) -> list[str]:
        return ["af_heart", "am_michael", "bf_emma"]

    def speak(self, text: str, voice: str, speed: float = 1.0) -> Iterator[Audio]:
        for sentence in sentences(text):
            self.spoken.append((voice, sentence))
            if self.delay_s:
                time.sleep(self.delay_s)
            yield tone(0.2, rate=self.rate)


def tone(seconds: float, *, rate: int = STT_RATE, amplitude: float = 0.3, hz: float = 220.0) -> Audio:
    t = np.arange(int(seconds * rate)) / rate
    return (amplitude * np.sin(2 * np.pi * hz * t)).astype(np.float32)


def silence(seconds: float, *, rate: int = STT_RATE) -> Audio:
    return np.zeros(int(seconds * rate), dtype=np.float32)


def utterances(*parts: tuple[str, float]) -> Audio:
    """("speech", 1.0), ("pause", 1.5)… → one buffer; "speech" is a tone loud enough for EnergyVAD."""
    return np.concatenate([tone(s) if kind == "speech" else silence(s) for kind, s in parts])
