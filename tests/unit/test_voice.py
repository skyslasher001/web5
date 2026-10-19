"""The voice package without models (Phase 7, ADR-0016): audio helpers, the Whisper front end, endpointing,
the session's modes, the wake phrase, numbers and phonemes, tickets, model installs, and Core's voice config."""

import hashlib
import io
import tarfile
from pathlib import Path

import numpy as np
import pytest

from tests.support.fake_voice import FakeSTT, silence, tone, utterances
from universe_core.voice_runtime import VoiceConfig, agent_voice, dump_config, load_config
from universe_voice import longform, models, tickets
from universe_voice.audio import STT_RATE, float_to_pcm16, level, pcm16_to_float, read_wav, resample, write_wav
from universe_voice.features import N_FRAMES, log_mel, mel_filters
from universe_voice.g2p import number_words, phonemize
from universe_voice.session import ARMED_S, VoiceSession
from universe_voice.stt import _repeating_tail
from universe_voice.tts import MAX_PHONEMES, _chunks, sentences, tokens, vocab
from universe_voice.vad import Endpointer, EnergyVAD
from universe_voice.wake import TranscriptWake

# ---------- audio ----------


def test_pcm16_round_trip_and_clipping() -> None:
    audio = np.array([0.0, 0.5, -0.5, 1.0, -1.0, 1.5], dtype=np.float32)
    back = pcm16_to_float(float_to_pcm16(audio))
    assert np.allclose(back[:5], [0, 0.5, -0.5, 1, -1], atol=1e-4)
    assert back[5] == pytest.approx(1.0, abs=1e-4)  # clipped, not wrapped


def test_level_and_resample() -> None:
    assert level(np.zeros(0, dtype=np.float32)) == 0.0
    assert 0.0 < level(tone(0.1, amplitude=0.1)) < level(tone(0.1, amplitude=0.3)) <= 1.0
    out = resample(tone(1.0, rate=24000), 24000, 16000)
    assert out.size == 16000 and out.dtype == np.float32
    # A 220 Hz tone stays 220 Hz: its spectrum peaks at the same frequency after resampling.
    peak = np.argmax(np.abs(np.fft.rfft(out))) * 16000 / out.size
    assert peak == pytest.approx(220, abs=2)


def test_wav_round_trip(tmp_path: Path) -> None:
    path = tmp_path / "a.wav"
    write_wav(path, tone(0.5), STT_RATE)
    audio, rate = read_wav(path)
    assert rate == STT_RATE and audio.size == 8000
    assert np.allclose(audio, tone(0.5), atol=1e-3)


# ---------- the Whisper front end ----------


def test_log_mel_matches_whisper_shapes_and_range() -> None:
    filters = mel_filters()
    assert filters.shape == (80, 201) and (filters >= 0).all()
    mel = log_mel(tone(2.0))
    assert mel.shape == (80, N_FRAMES)  # always a full 30 s window, padded
    assert mel.max() <= 1.5 and mel.min() >= mel.max() - 2.0 - 1e-6  # floored at max − 8 dB, scaled by 1/4
    # Speech energy shows up in the first 2 s, the padding is flat.
    assert mel[:, :150].mean() > mel[:, 400:].mean()


def test_repetition_guard_cuts_a_stuck_loop() -> None:
    assert _repeating_tail([1, 2, 3, 4]) == 0
    assert _repeating_tail([9, 7, 7, 7, 7, 7, 7]) == 5  # keep one 7
    assert _repeating_tail([1, 5, 6, 5, 6, 5, 6, 5, 6, 5, 6]) == 8


# ---------- endpointing ----------


def test_endpointer_finds_utterances_with_preroll() -> None:
    ep = Endpointer(EnergyVAD())
    audio = utterances(("pause", 1.0), ("speech", 1.0), ("pause", 1.0), ("speech", 0.6), ("pause", 1.0))
    events = ep.feed(audio)
    starts = [e for e in events if e.started]
    ends = [e.ended for e in events if e.ended is not None]
    assert len(starts) == 2 and len(ends) == 2
    # First utterance: 1 s of speech, plus pre-roll and the hang-over silence that ended it.
    assert 1.0 < ends[0].size / STT_RATE < 2.2
    assert not ep.in_speech


def test_endpointer_ignores_clicks_and_caps_long_speech() -> None:
    ep = Endpointer(EnergyVAD(), max_s=2.0)
    assert ep.feed(utterances(("pause", 0.5), ("speech", 0.1), ("pause", 1.0))) == []  # too short to count
    events = ep.feed(utterances(("speech", 5.0)))
    assert sum(e.ended is not None for e in events) >= 2  # cut at 2 s, never one endless utterance


# ---------- the session ----------


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def session(lines: list[str], mode: str = "push_to_talk", **kw: object) -> tuple[VoiceSession, list[dict], Clock]:
    events: list[dict] = []
    clock = Clock()
    s = VoiceSession(
        stt=FakeSTT(lines),
        endpointer=Endpointer(EnergyVAD()),
        emit=events.append,
        clock=clock,
        **kw,  # type: ignore[arg-type]
    )
    if mode != "push_to_talk":
        s.set_mode(mode)  # type: ignore[arg-type]
    return s, events, clock


def finals(events: list[dict]) -> list[str]:
    return [e["text"] for e in events if e["type"] == "final"]


def test_push_to_talk_transcribes_only_while_held() -> None:
    s, events, _ = session(["take me to Ember Wolf"])
    s.feed(tone(1.0))  # not held: ignored
    s.push(True)
    s.feed(tone(1.0))
    s.push(False)
    assert finals(events) == ["take me to Ember Wolf"]
    assert next(e for e in events if e["type"] == "final")["waited_s"] == 0  # releasing the key ends it at once
    assert s.stt.heard == [pytest.approx(1.0, abs=0.01)]  # type: ignore[attr-defined]
    s.push(True)
    s.feed(tone(0.1))  # a tap, not speech
    s.push(False)
    assert len(finals(events)) == 1 and events[-1] == {"type": "state", "state": "idle"}


def test_wake_mode_needs_the_phrase() -> None:
    s, events, _ = session(["what's the weather", "Hey Universe, show photos from the lake."], mode="wake")
    s.feed(utterances(("pause", 0.5), ("speech", 1.0), ("pause", 1.0)))
    assert finals(events) == [] and any(e["type"] == "ignored" for e in events)
    s.feed(utterances(("speech", 1.0), ("pause", 1.0)))
    assert finals(events) == ["show photos from the lake."]
    # Hands-free, the end of speech is known only after the hang-over silence; the latency figure counts it.
    assert next(e for e in events if e["type"] == "final")["waited_s"] == s.endpointer.hangover_s


def test_a_bare_wake_phrase_arms_the_next_utterance() -> None:
    s, events, clock = session(["Hey Universe.", "go home", "go home"], mode="wake")
    s.feed(utterances(("pause", 0.5), ("speech", 0.8), ("pause", 1.0)))
    assert any(e["type"] == "wake" for e in events) and finals(events) == []
    s.feed(utterances(("speech", 0.8), ("pause", 1.0)))
    assert finals(events) == ["go home"]
    clock.now += ARMED_S + 1  # armed once only: the next one needs the phrase again
    s.feed(utterances(("speech", 0.8), ("pause", 1.0)))
    assert finals(events) == ["go home"]


def test_continuous_mode_times_out_back_to_wake() -> None:
    s, events, clock = session(["open the agents panel"], mode="continuous", continuous_timeout_s=30)
    s.feed(utterances(("pause", 0.5), ("speech", 1.0), ("pause", 1.0)))
    assert finals(events) == ["open the agents panel"]
    clock.now += 31
    s.feed(silence(0.1))
    assert {"type": "timeout"} in events and s.mode == "wake"


def test_speaking_over_an_answer_is_a_barge_in() -> None:
    s, events, _ = session(["stop"], mode="continuous")
    s.set_playing(True)
    s.feed(utterances(("pause", 0.5), ("speech", 1.0)))
    assert {"type": "barge_in"} in events and s.playing is False
    s, events, _ = session(["x"], mode="continuous")
    s.feed(utterances(("pause", 0.5), ("speech", 1.0)))
    assert {"type": "barge_in"} not in events  # nothing playing: not an interruption


# ---------- wake phrase ----------


@pytest.mark.parametrize(
    ("heard", "command"),
    [
        ("Hey Universe, take me to Ember Wolf.", "take me to Ember Wolf."),
        ("hey universe", ""),
        ("Hey, Universe! Open chat", "Open chat"),
        ("Hey universes, go home", "go home"),  # Whisper's near-misses still wake
    ],
)
def test_wake_phrase_matches(heard: str, command: str) -> None:
    match = TranscriptWake().match(heard)
    assert match is not None and match.command == command


def test_wake_phrase_rejects_other_speech_and_follows_your_phrase() -> None:
    assert TranscriptWake().match("Take me to Ember Wolf") is None
    assert TranscriptWake().match("") is None
    assert TranscriptWake("computer").match("Computer, zoom in") is not None
    assert TranscriptWake("computer").match("Hey Universe, zoom in") is None


# ---------- numbers, phonemes, Kokoro tokens ----------


@pytest.mark.parametrize(
    ("number", "words"),
    [
        ("0", "zero"),
        ("42", "forty two"),
        ("2026", "twenty twenty six"),
        ("1905", "nineteen oh five"),
        ("1234", "one thousand two hundred thirty four"),
        ("3.5", "three point five"),
        ("1000000", "one million"),
    ],
)
def test_numbers_are_read_aloud(number: str, words: str) -> None:
    assert number_words(number) == words


def test_phonemes_become_kokoro_tokens() -> None:
    ipa = phonemize("Flying to Ember Wolf. It has 12 items!")
    assert ipa and "." in ipa and "!" in ipa
    ids = tokens(ipa)
    assert ids and all(0 < i < 200 for i in ids)
    assert len(vocab()) == 114
    assert phonemize("NASA") and phonemize("UNIVERSE")  # unknown capitals are still spoken


def test_sentences_and_long_sentence_chunks() -> None:
    assert sentences("Flying to Ember Wolf. It has twelve items! Ready?") == [
        "Flying to Ember Wolf.",
        "It has twelve items!",
        "Ready?",
    ]
    space = vocab()[" "]
    ids = ([5, 6, 7, space] * 300)[:-1]
    parts = _chunks(ids, space)
    assert all(len(p) <= MAX_PHONEMES for p in parts) and len(parts) >= 2
    assert sum(len(p) for p in parts) + len(parts) - 1 == len(ids)  # only the split spaces are dropped


# ---------- tickets ----------


def test_tickets_work_once_and_expire() -> None:
    key = b"k" * 32
    now = [1000.0]
    checker = tickets.TicketChecker(key, now=lambda: now[0])
    ticket = tickets.mint(key, now=lambda: now[0])
    assert checker.check(ticket) is True
    assert checker.check(ticket) is False  # single use
    late = tickets.mint(key, ttl_s=5, now=lambda: now[0])
    now[0] += 6
    assert checker.check(late) is False  # expired
    assert checker.check(tickets.mint(b"x" * 32, now=lambda: now[0])) is False  # another key
    body, _, sig = tickets.mint(key, now=lambda: now[0]).partition(".")
    assert checker.check(f"{body}x.{sig}") is False  # tampered
    assert checker.check("") is False and checker.check("no-dot") is False


# ---------- model installs ----------


def _download(data: bytes, url: str = "https://example.com/m.onnx", members: tuple[str, ...] = ()) -> models.Download:
    return models.Download(url, hashlib.sha256(data).hexdigest(), len(data), members)


def test_place_installs_a_verified_file_and_refuses_a_tampered_one(tmp_path: Path) -> None:
    data = b"model" * 100
    model = models.VoiceModel("m", "vad", "t", "MIT", "x", (_download(data),), ("m.onnx",))
    bad = tmp_path / "bad.part"
    bad.write_bytes(data[:-1] + b"X")
    with pytest.raises(models.InstallError, match="pinned SHA-256"):
        models.place(tmp_path / "models", model, model.downloads[0], bad)
    assert not models.installed(tmp_path / "models", model)
    good = tmp_path / "good.part"
    good.write_bytes(data)
    models.place(tmp_path / "models", model, model.downloads[0], good)
    assert models.installed(tmp_path / "models", model) and not good.exists()


def test_place_extracts_only_the_listed_members_flat(tmp_path: Path) -> None:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:bz2") as tar:
        for name, payload in (("pkg/a.onnx", b"a"), ("pkg/b.txt", b"b"), ("pkg/test_wavs/x.wav", b"x")):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    data = buf.getvalue()
    download = _download(data, "https://example.com/m.tar.bz2", ("a.onnx", "b.txt"))
    model = models.VoiceModel("w", "stt", "t", "MIT", "x", (download,), ("a.onnx", "b.txt"))
    part = tmp_path / "m.part"
    part.write_bytes(data)
    models.place(tmp_path / "models", model, download, part)
    assert sorted(p.name for p in (tmp_path / "models" / "w").iterdir()) == ["a.onnx", "b.txt"]
    missing = models.Download(download.url, download.sha256, download.size, ("a.onnx", "nope.onnx"))
    part.write_bytes(data)
    with pytest.raises(models.InstallError, match=r"missing nope\.onnx"):
        models.place(tmp_path / "m2", model, missing, part)


def test_catalog_pins_every_download() -> None:
    for model in models.CATALOG:
        assert model.downloads and model.files
        for d in model.downloads:
            assert d.url.startswith("https://") and len(d.sha256) == 64 and d.size > 1_000_000


# ---------- long recordings ----------


def test_speech_spans_skip_silence_merge_short_pauses_and_split_long_speech() -> None:
    audio = utterances(
        ("pause", 1.0), ("speech", 1.0), ("pause", 0.3), ("speech", 0.5), ("pause", 2.0), ("speech", 40.0)
    )
    spans = longform.speech_spans(audio, EnergyVAD())
    seconds = [(a / STT_RATE, b / STT_RATE) for a, b in spans]
    # 1.0–2.0 s and 2.3–2.8 s are one span (the 0.3 s pause is merged), padded by 0.2 s.
    assert seconds[0][0] == pytest.approx(0.8, abs=0.1) and seconds[0][1] == pytest.approx(3.0, abs=0.15)
    assert all(b - a <= longform.MAX_SEGMENT_S + 1e-6 for a, b in seconds)
    assert len(spans) >= 3  # the 40 s monologue is split into Whisper-sized pieces


def test_longform_without_ffmpeg_says_why(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(longform, "ffmpeg", lambda: None)
    song = tmp_path / "a.m4a"
    song.write_bytes(b"\x00" * 10)
    with pytest.raises(longform.Undecodable, match="needs ffmpeg on PATH"):
        longform.load_audio(song)
    broken = tmp_path / "b.wav"
    broken.write_bytes(b"RIFF....nope")
    with pytest.raises(longform.Undecodable):
        longform.load_audio(broken)


# ---------- Core's voice config ----------


def test_agents_get_their_own_voices_and_your_picks_win() -> None:
    config = VoiceConfig()
    assert agent_voice(config, "core", "calm-neutral") == "af_heart"
    assert agent_voice(config, "forge", None) == "am_onyx"  # protected YAML: the code fallback
    assert agent_voice(config, "mine", None) == config.voice
    assert agent_voice(config, "mine", "bf_alice") == "bf_alice"  # a Kokoro id works directly
    config.agents["core"] = "am_eric"
    assert agent_voice(config, "core", "calm-neutral") == "am_eric"


def test_voice_config_round_trips_and_survives_junk() -> None:
    config = VoiceConfig(stt="whisper-base.en", wake_phrase="computer", mode="wake", agents={"core": "am_eric"})
    assert load_config(dump_config(config)) == config
    assert load_config(None) == VoiceConfig()
    assert load_config("not json") == VoiceConfig()
    assert load_config('{"mode": "continuous", "unknown": 1}').mode == "continuous"
    assert load_config("[1, 2]") == VoiceConfig()
