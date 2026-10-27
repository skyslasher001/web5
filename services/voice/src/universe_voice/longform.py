"""Transcribing a whole recording (SPEC §5.5: audio and video, with timestamps).

The vault worker uses this for voice memos, audio and video: decode to 16 kHz mono, find the stretches of speech
with the VAD, and transcribe each one (at most 30 s, Whisper's window), so every chunk of the transcript knows
where it is in the recording.

Decoding: WAV is read with the standard library. Anything else (MP3, M4A, video…) needs an `ffmpeg` executable on
PATH, which runs as a separate, unmodified process (ADR-0008: copyleft only as a separate process). Without it,
those files are skipped with that reason.
"""

import shutil
import subprocess
import sys
import wave
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from universe_voice.audio import STT_RATE, Audio, read_wav, resample
from universe_voice.stt import STT
from universe_voice.vad import FRAME, VAD

FRAME_S = FRAME / STT_RATE
MAX_SEGMENT_S = 28.0  # under Whisper's 30 s window, with room for the padding
PAD_S = 0.2
MERGE_GAP_S = 0.6  # pauses shorter than this stay inside one segment
MIN_SPEECH_S = 0.3
MAX_DURATION_S = 3 * 3600.0  # longer recordings are skipped (a background job shouldn't run for hours)


class Undecodable(Exception):
    """The file can't be turned into audio here (no decoder for its format, or it has no audio)."""


@dataclass(frozen=True)
class Piece:
    start_ms: int
    end_ms: int
    text: str


def ffmpeg() -> str | None:
    return shutil.which("ffmpeg")


def load_audio(path: Path, *, max_s: float = MAX_DURATION_S) -> Audio:
    """The recording as 16 kHz mono float32."""
    if path.suffix.lower() == ".wav":
        try:
            audio, rate = read_wav(path)
        except (wave.Error, ValueError, EOFError, OSError) as exc:  # compressed, 24-bit or broken WAVs
            raise Undecodable(f"{path.name}: {exc}") from exc
        if audio.size > max_s * rate:
            raise Undecodable(f"longer than {max_s / 3600:.0f} h; not transcribed")
        return resample(audio, rate, STT_RATE)
    exe = ffmpeg()
    if exe is None:
        raise Undecodable(f"decoding {path.suffix or 'this file'} needs ffmpeg on PATH (WAV works without it)")
    command = [exe, "-nostdin", "-v", "error", "-i", str(path), "-t", str(int(max_s) + 1)]
    command += ["-vn", "-ac", "1", "-ar", str(STT_RATE), "-f", "s16le", "-"]
    flags = 0x08000000 if sys.platform == "win32" else 0  # CREATE_NO_WINDOW
    result = subprocess.run(command, capture_output=True, timeout=600, check=False, creationflags=flags)
    if result.returncode != 0 or not result.stdout:
        reason = result.stderr.decode("utf-8", "replace").strip().splitlines()[-1:] or ["no audio stream"]
        raise Undecodable(f"ffmpeg couldn't decode it: {reason[0][:200]}")
    audio = np.frombuffer(result.stdout[: len(result.stdout) // 2 * 2], dtype="<i2").astype(np.float32) / 32768.0
    if audio.size > max_s * STT_RATE:
        raise Undecodable(f"longer than {max_s / 3600:.0f} h; not transcribed")
    return audio


def speech_spans(audio: Audio, vad: VAD, threshold: float = 0.5) -> list[tuple[int, int]]:
    """Sample ranges that contain speech: merged across short pauses, padded, and at most MAX_SEGMENT_S long."""
    vad.reset()
    frames = audio.size // FRAME
    voiced = [vad.prob(audio[i * FRAME : (i + 1) * FRAME]) >= threshold for i in range(frames)]
    spans: list[list[int]] = []
    for i, speaking in enumerate(voiced):
        if not speaking:
            continue
        if spans and (i - spans[-1][1]) * FRAME_S <= MERGE_GAP_S:
            spans[-1][1] = i + 1
        else:
            spans.append([i, i + 1])
    pad, longest = int(PAD_S * STT_RATE), int(MAX_SEGMENT_S * STT_RATE)
    out: list[tuple[int, int]] = []
    for first, last in spans:
        if (last - first) * FRAME_S < MIN_SPEECH_S:
            continue
        start, end = max(0, first * FRAME - pad), min(audio.size, last * FRAME + pad)
        while end - start > longest:  # split long monologues at the window size
            out.append((start, start + longest))
            start += longest
        out.append((start, end))
    return out


def transcribe(audio: Audio, stt: STT, vad: VAD, *, progress: Callable[[float], None] | None = None) -> list[Piece]:
    pieces = []
    spans = speech_spans(audio, vad)
    for n, (start, end) in enumerate(spans):
        text = stt.transcribe(audio[start:end]).text.strip()
        if text:
            pieces.append(Piece(start * 1000 // STT_RATE, end * 1000 // STT_RATE, text))
        if progress:
            progress((n + 1) / len(spans))
    return pieces
