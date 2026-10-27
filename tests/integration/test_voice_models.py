"""Voice with the real models (Phase 7): Kokoro speaks SPEC's own commands, Silero finds them, Whisper writes them
down, and the wake phrase and a vault memo work end to end. Runs when UNIVERSE_TEST_VOICE_MODELS points at a
folder of installed models (System → Voice installs them to <data dir>/models/voice); skipped otherwise, because
CI can't download ~250 MB of models."""

import os
import re
import time
from pathlib import Path

import numpy as np
import pytest

from universe_vault.transcription import Transcriber
from universe_voice.audio import STT_RATE, TTS_RATE, resample, write_wav
from universe_voice.models import BY_ID, folder, installed
from universe_voice.session import VoiceSession
from universe_voice.stt import WhisperOnnx
from universe_voice.tts import KokoroTTS
from universe_voice.vad import Endpointer, SileroVAD

ROOT = Path(os.environ.get("UNIVERSE_TEST_VOICE_MODELS", "/nonexistent"))
NEEDED = ("whisper-tiny.en", "kokoro-82m", "silero-vad")
pytestmark = pytest.mark.skipif(
    not all(installed(ROOT, BY_ID[m]) for m in NEEDED),
    reason="set UNIVERSE_TEST_VOICE_MODELS to a folder with whisper-tiny.en, kokoro-82m and silero-vad installed",
)


@pytest.fixture(scope="module")
def tts() -> KokoroTTS:
    k = BY_ID["kokoro-82m"]
    return KokoroTTS(folder(ROOT, k) / k.files[0], folder(ROOT, k) / k.files[1])


@pytest.fixture(scope="module")
def stt() -> WhisperOnnx:
    return WhisperOnnx(folder(ROOT, BY_ID["whisper-tiny.en"]))


def vad() -> SileroVAD:
    return SileroVAD(folder(ROOT, BY_ID["silero-vad"]) / "silero_vad.onnx")


def spoken(tts: KokoroTTS, text: str, voice: str = "am_michael") -> np.ndarray:
    audio = np.concatenate(list(tts.speak(text, voice)))
    pad = np.zeros(int(0.5 * STT_RATE), dtype=np.float32)
    return np.concatenate([pad, resample(audio, TTS_RATE, STT_RATE), pad, pad])


def norm(text: str) -> str:
    return re.sub(r"[^a-z ]", "", text.lower()).strip()


@pytest.mark.parametrize(
    "command",
    ["Take me to Ember Wolf.", "Show photos from the lake.", "Play the song I made in March.", "Forge, what broke?"],
)
def test_round_trip_of_spec_commands(tts: KokoroTTS, stt: WhisperOnnx, command: str) -> None:
    audio = spoken(tts, command)
    events = Endpointer(vad()).feed(audio)
    [utterance] = [e.ended for e in events if e.ended is not None]
    result = stt.transcribe(utterance)
    assert norm(result.text) == norm(command)
    # The STT share of the 1.5 s budget (SPEC §21), on whatever CPU runs this.
    assert result.seconds < 1.0, f"Whisper tiny.en took {result.seconds:.2f}s for {utterance.size / STT_RATE:.1f}s"


def test_first_spoken_sentence_is_quick(tts: KokoroTTS) -> None:
    started = time.perf_counter()
    first = next(tts.speak("Flying to Ember Wolf Acquisitions. It has twelve items.", "af_heart"))
    took = time.perf_counter() - started
    assert first.size > TTS_RATE // 2  # the first sentence alone, not the whole answer
    assert took < 1.0, f"Kokoro took {took:.2f}s for the first sentence"


def test_wake_phrase_then_command(tts: KokoroTTS, stt: WhisperOnnx) -> None:
    events: list[dict] = []
    session = VoiceSession(stt=stt, endpointer=Endpointer(vad()), emit=events.append)
    session.set_mode("wake")
    session.feed(spoken(tts, "What a nice day."))
    session.feed(spoken(tts, "Hey Universe, open the agents panel."))
    finals = [e["text"] for e in events if e["type"] == "final"]
    assert [norm(t) for t in finals] == ["open the agents panel"]
    assert any(e["type"] == "ignored" for e in events)


def test_a_memo_is_transcribed_with_timestamps(tts: KokoroTTS, tmp_path: Path) -> None:
    memo = tmp_path / "memo.wav"
    one, two = spoken(tts, "Call the seller about the lake parcel."), spoken(tts, "The bridge should go up a key.")
    write_wav(memo, np.concatenate([one, np.zeros(STT_RATE, dtype=np.float32), two]), STT_RATE)
    pieces = Transcriber(ROOT)(memo)
    assert [norm(p.text) for p in pieces] == [
        norm("Call the seller about the lake parcel."),
        norm("The bridge should go up a key."),
    ]
    assert pieces[0].end_ms <= pieces[1].start_ms
