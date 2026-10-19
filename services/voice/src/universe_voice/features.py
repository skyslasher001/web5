"""Whisper's log-mel front end in numpy (no torch, no librosa).

Matches openai/whisper `log_mel_spectrogram`: 16 kHz audio padded to 30 s, a 400-point periodic Hann STFT with
hop 160 and reflect padding, power spectrum without the last frame, an 80-band Slaney mel filter bank
(librosa's formula, htk=False, norm="slaney"), log10 clamped to 8 decades below the peak, scaled by (x + 4) / 4.
"""

from functools import cache

import numpy as np
from numpy.typing import NDArray

from universe_voice.audio import STT_RATE, Audio

N_FFT = 400
HOP = 160
CHUNK_SAMPLES = 30 * STT_RATE  # Whisper always sees 30 s windows
N_FRAMES = CHUNK_SAMPLES // HOP  # 3000


def _hz_to_mel(hz: NDArray[np.float64]) -> NDArray[np.float64]:
    """Slaney mel scale: linear below 1 kHz, logarithmic above."""
    f_sp, min_log_hz = 200.0 / 3, 1000.0
    min_log_mel, logstep = min_log_hz / f_sp, np.log(6.4) / 27.0
    mel = hz / f_sp
    log_region = hz >= min_log_hz
    mel[log_region] = min_log_mel + np.log(hz[log_region] / min_log_hz) / logstep
    return mel


def _mel_to_hz(mel: NDArray[np.float64]) -> NDArray[np.float64]:
    f_sp, min_log_hz = 200.0 / 3, 1000.0
    min_log_mel, logstep = min_log_hz / f_sp, np.log(6.4) / 27.0
    hz = mel * f_sp
    log_region = mel >= min_log_mel
    hz[log_region] = min_log_hz * np.exp(logstep * (mel[log_region] - min_log_mel))
    return hz


@cache
def mel_filters(n_mels: int = 80, sr: int = STT_RATE, n_fft: int = N_FFT) -> NDArray[np.float32]:
    fft_freqs = np.fft.rfftfreq(n=n_fft, d=1.0 / sr)
    mel_points = np.linspace(0.0, _hz_to_mel(np.array([sr / 2.0]))[0], n_mels + 2)
    hz_points = _mel_to_hz(mel_points)
    fdiff = np.diff(hz_points)
    ramps = np.subtract.outer(hz_points, fft_freqs)
    lower = -ramps[:-2] / fdiff[:-1][:, None]
    upper = ramps[2:] / fdiff[1:][:, None]
    weights = np.maximum(0.0, np.minimum(lower, upper))
    weights *= (2.0 / (hz_points[2 : n_mels + 2] - hz_points[:n_mels]))[:, None]  # Slaney area normalization
    return weights.astype(np.float32)


@cache
def _window() -> NDArray[np.float64]:
    return np.hanning(N_FFT + 1)[:-1]  # periodic Hann, like torch.hann_window(400)


def log_mel(audio: Audio, n_mels: int = 80) -> NDArray[np.float32]:
    """(n_mels, 3000) features for one 30-second window; longer audio is cut, shorter is zero-padded."""
    x = np.zeros(CHUNK_SAMPLES, dtype=np.float64)
    clip = audio[:CHUNK_SAMPLES]
    x[: clip.size] = clip
    padded = np.pad(x, (N_FFT // 2, N_FFT // 2), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(padded, N_FFT)[::HOP]
    power = np.abs(np.fft.rfft(frames * _window(), axis=-1)) ** 2  # (3001, 201)
    mel = mel_filters(n_mels) @ power[:-1].T  # drop the last frame → (n_mels, 3000)
    log_spec = np.log10(np.maximum(mel, 1e-10))
    log_spec = np.maximum(log_spec, log_spec.max() - 8.0)
    return ((log_spec + 4.0) / 4.0).astype(np.float32)
