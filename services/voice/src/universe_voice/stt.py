"""Speech to text: Whisper on ONNX Runtime (ADR-0016).

The model is the k2-fsa/sherpa-onnx export of OpenAI's Whisper weights (MIT): an encoder that turns a 30-second
log-mel window into cross-attention keys and values, and a decoder that takes tokens plus a preallocated
self-attention cache and an offset. Special-token ids and sizes come from the encoder's own metadata, so the
same code runs tiny.en through large-v3-turbo. Greedy decoding without timestamps: voice commands are short,
and longer dictation is cut into 30-second windows.
"""

import base64
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np
import onnxruntime as ort

from universe_voice.audio import Audio
from universe_voice.features import CHUNK_SAMPLES, log_mel


@dataclass
class Transcript:
    text: str
    seconds: float  # wall time spent transcribing


class STT(Protocol):
    name: str

    def transcribe(self, audio: Audio) -> Transcript: ...


def providers() -> list[str]:
    """GPU when ONNX Runtime has one (CUDA, or DirectML on any Windows GPU), else CPU."""
    available = ort.get_available_providers()
    preferred = ["CUDAExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"]
    return [p for p in preferred if p in available] or ["CPUExecutionProvider"]


def session(path: Path, threads: int = 0) -> ort.InferenceSession:
    options = ort.SessionOptions()
    options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    if threads:
        options.intra_op_num_threads = threads
    options.log_severity_level = 3  # errors only
    return ort.InferenceSession(str(path), sess_options=options, providers=providers())


def _repeating_tail(tokens: list[int], times: int = 5) -> int:
    """How many trailing tokens are a stuck loop (an n-gram repeated `times`+ in a row); 0 when there's none."""
    for n in range(1, 5):
        if len(tokens) < n * times:
            continue
        gram = tokens[-n:]
        reps = 1
        while len(tokens) >= n * (reps + 1) and tokens[-n * (reps + 1) : -n * reps] == gram:
            reps += 1
        if reps >= times:
            return n * (reps - 1)  # keep one copy
    return 0


class WhisperOnnx:
    """Whisper from a model directory holding `<name>-encoder[.int8].onnx`, `-decoder…` and `-tokens.txt`."""

    def __init__(self, model_dir: Path, *, int8: bool = True, threads: int = 0) -> None:
        encoders = sorted(model_dir.glob("*-encoder*.onnx"))
        if not encoders:
            raise FileNotFoundError(f"no Whisper encoder in {model_dir}")
        prefix = encoders[0].name.split("-encoder")[0]
        suffix = ".int8.onnx" if int8 and (model_dir / f"{prefix}-encoder.int8.onnx").exists() else ".onnx"
        self.name = f"whisper:{prefix}"
        self._encoder = session(model_dir / f"{prefix}-encoder{suffix}", threads)
        self._decoder = session(model_dir / f"{prefix}-decoder{suffix}", threads)
        meta = self._encoder.get_modelmeta().custom_metadata_map
        self.eot = int(meta["eot"])
        self.blank = int(meta.get("blank_id", "220"))
        self.n_layer = int(meta["n_text_layer"])
        self.n_ctx = int(meta["n_text_ctx"])
        self.n_state = int(meta["n_text_state"])
        self.n_mels = int(meta.get("n_mels", "80"))
        self.non_speech = [int(t) for t in meta.get("non_speech_tokens", "").split(",") if t]
        sot = [int(t) for t in meta["sot_sequence"].split(",")]
        if meta.get("is_multilingual") == "1":  # English only (owner decision): <|en|><|transcribe|>
            codes = meta["all_language_codes"].split(",")
            ids = [int(t) for t in meta["all_language_tokens"].split(",")]
            sot = [int(meta["sot"]), ids[codes.index("en")], int(meta["transcribe"])]
        self.prompt = [*sot, int(meta["no_timestamps"])]
        self._bytes: dict[int, bytes] = {}
        for line in (model_dir / f"{prefix}-tokens.txt").read_text(encoding="utf-8").splitlines():
            b64, _, idx = line.rpartition(" ")
            if b64:
                self._bytes[int(idx)] = base64.b64decode(b64)

    def _decode_window(self, audio: Audio) -> list[int]:
        mel = log_mel(audio, self.n_mels)[None]
        cross_k, cross_v = (np.asarray(x) for x in self._encoder.run(None, {"mel": mel}))
        cache_shape = (self.n_layer, 1, self.n_ctx, self.n_state)
        self_k = np.zeros(cache_shape, dtype=np.float32)
        self_v = np.zeros(cache_shape, dtype=np.float32)
        tokens = np.array([self.prompt], dtype=np.int64)
        offset = 0
        out: list[int] = []
        for step in range(self.n_ctx // 2 - len(self.prompt)):
            logits, self_k, self_v = self._decoder.run(
                None,
                {
                    "tokens": tokens,
                    "in_n_layer_self_k_cache": self_k,
                    "in_n_layer_self_v_cache": self_v,
                    "n_layer_cross_k": cross_k,
                    "n_layer_cross_v": cross_v,
                    "offset": np.array([offset], dtype=np.int64),
                },
            )
            offset += tokens.shape[1]
            logit = np.asarray(logits)[0, -1].astype(np.float32)
            logit[self.eot + 1 :] = -np.inf  # no timestamps, task or language tokens
            if self.non_speech:
                logit[self.non_speech] = -np.inf
            if step == 0:
                logit[[self.blank, self.eot]] = -np.inf  # don't start with a space or stop at once
            token = int(np.argmax(logit))
            if token == self.eot:
                break
            out.append(token)
            if cut := _repeating_tail(out):
                del out[-cut:]
                break
            tokens = np.array([[token]], dtype=np.int64)
        return out

    def transcribe(self, audio: Audio) -> Transcript:
        started = time.perf_counter()
        pieces = []
        for start in range(0, max(audio.size, 1), CHUNK_SAMPLES):
            ids = self._decode_window(audio[start : start + CHUNK_SAMPLES])
            pieces.append(b"".join(self._bytes.get(t, b"") for t in ids).decode("utf-8", errors="replace"))
        text = " ".join(p.strip() for p in pieces if p.strip())
        return Transcript(text=text, seconds=time.perf_counter() - started)
