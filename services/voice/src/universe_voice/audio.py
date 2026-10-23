"""PCM helpers: the formats the voice pipeline speaks.

On the wire, audio is little-endian signed 16-bit mono. Inside, it's float32 in [-1, 1]. Capture arrives at
16 kHz (the renderer's AudioContext resamples the mic); Kokoro speaks at 24 kHz.
"""

import wave
from pathlib import Path

import numpy as np
from numpy.typing import NDArray

STT_RATE = 16_000
TTS_RATE = 24_000

Audio = NDArray[np.float32]


def pcm16_to_float(data: bytes) -> Audio:
    return np.frombuffer(data, dtype="<i2").astype(np.float32) / 32768.0


def float_to_pcm16(audio: Audio) -> bytes:
    return (np.clip(audio, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()


def level(audio: Audio) -> float:
    """RMS level in [0, 1] for the orb's waveform; 0 for an empty buffer."""
    if audio.size == 0:
        return 0.0
    return float(min(1.0, np.sqrt(np.mean(np.square(audio, dtype=np.float64))) * 4.0))


def resample(audio: Audio, src_rate: int, dst_rate: int) -> Audio:
    """Band-limited resampling of a whole buffer (FFT method), e.g. Kokoro's 24 kHz down to 16 kHz.

    Truncating the spectrum is the low-pass, so downsampling doesn't alias. Live capture never comes through
    here: the renderer's AudioContext already delivers 16 kHz.
    """
    if src_rate == dst_rate or audio.size == 0:
        return audio.astype(np.float32, copy=False)
    n_out = round(audio.size * dst_rate / src_rate)
    spectrum = np.fft.rfft(audio.astype(np.float64))
    kept = np.zeros(n_out // 2 + 1, dtype=np.complex128)
    n = min(kept.size, spectrum.size)
    kept[:n] = spectrum[:n]
    return (np.fft.irfft(kept, n=n_out) * (n_out / audio.size)).astype(np.float32)


def read_wav(path: Path) -> tuple[Audio, int]:
    """A mono (or first-channel) 16-bit WAV as float32 and its sample rate."""
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise ValueError(f"{path.name}: only 16-bit PCM WAV is supported")
        channels, rate = w.getnchannels(), w.getframerate()
        data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
    if channels > 1:
        data = data[::channels]
    return data.astype(np.float32) / 32768.0, rate


def write_wav(path: Path, audio: Audio, rate: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(float_to_pcm16(audio))
