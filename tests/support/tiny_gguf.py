"""Write a tiny random-weight llama-architecture GGUF file (pure Python, no dependencies).

Test fixture only: it lets the integration tests drive a *real* Ollama server without downloading a
model. The output is gibberish biased towards a few English words. Format: GGUF v3, F32 tensors.
"""

import random
import struct
from array import array
from pathlib import Path

ALIGNMENT = 32
_U32, _F32, _BOOL, _STRING, _ARRAY = 4, 6, 7, 8, 9

WORDS = ["▁hello", "▁universe", "▁core", "▁online", "▁local", "▁model", "."]


def _string(value: str) -> bytes:
    data = value.encode("utf-8")
    return struct.pack("<Q", len(data)) + data


def _kv(key: str, value: object) -> bytes:
    out = _string(key)
    if isinstance(value, bool):
        return out + struct.pack("<I?", _BOOL, value)
    if isinstance(value, int):
        return out + struct.pack("<II", _U32, value)
    if isinstance(value, float):
        return out + struct.pack("<If", _F32, value)
    if isinstance(value, str):
        return out + struct.pack("<I", _STRING) + _string(value)
    if isinstance(value, list):
        first = value[0]
        if isinstance(first, str):
            body = b"".join(_string(v) for v in value)
            return out + struct.pack("<IIQ", _ARRAY, _STRING, len(value)) + body
        if isinstance(first, float):
            return out + struct.pack("<IIQ", _ARRAY, _F32, len(value)) + struct.pack(f"<{len(value)}f", *value)
        return out + struct.pack("<IIQ", _ARRAY, 5, len(value)) + struct.pack(f"<{len(value)}i", *value)  # INT32
    raise TypeError(f"unsupported metadata value for {key}: {value!r}")


def write_tiny_llama(path: Path, *, seed: int = 1) -> Path:
    rng = random.Random(seed)  # noqa: S311 - deterministic test weights, not security
    n_embd, n_ff, n_head, n_ctx = 64, 128, 4, 512
    tokens = ["<unk>", "<s>", "</s>"] + [f"<0x{i:02X}>" for i in range(256)] + WORDS
    types = [2, 3, 3] + [6] * 256 + [1] * len(WORDS)
    n_vocab = len(tokens)
    metadata = {
        "general.architecture": "llama",
        "general.name": "universe-test-tiny",
        "general.alignment": ALIGNMENT,
        "general.file_type": 0,
        "llama.context_length": n_ctx,
        "llama.embedding_length": n_embd,
        "llama.block_count": 1,
        "llama.feed_forward_length": n_ff,
        "llama.attention.head_count": n_head,
        "llama.attention.head_count_kv": n_head,
        "llama.rope.dimension_count": n_embd // n_head,
        "llama.attention.layer_norm_rms_epsilon": 1e-5,
        "tokenizer.ggml.model": "llama",
        "tokenizer.ggml.tokens": tokens,
        "tokenizer.ggml.scores": [0.0] * n_vocab,
        "tokenizer.ggml.token_type": types,
        "tokenizer.ggml.bos_token_id": 1,
        "tokenizer.ggml.eos_token_id": 2,
        "tokenizer.ggml.unknown_token_id": 0,
        "tokenizer.ggml.add_bos_token": True,
    }

    def normal(count: int, scale: float = 0.02) -> array:
        return array("f", (rng.gauss(0.0, scale) for _ in range(count)))

    output = normal(n_vocab * n_embd)
    for i in range((3 + 256) * n_embd, n_vocab * n_embd):  # favour the word tokens
        output[i] *= 25
    # name -> (shape as ggml dims: fastest-varying first, data)
    tensors: list[tuple[str, tuple[int, ...], array]] = [
        ("token_embd.weight", (n_embd, n_vocab), normal(n_vocab * n_embd)),
        ("output_norm.weight", (n_embd,), array("f", [1.0] * n_embd)),
        ("output.weight", (n_embd, n_vocab), output),
        ("blk.0.attn_norm.weight", (n_embd,), array("f", [1.0] * n_embd)),
        ("blk.0.attn_q.weight", (n_embd, n_embd), normal(n_embd * n_embd)),
        ("blk.0.attn_k.weight", (n_embd, n_embd), normal(n_embd * n_embd)),
        ("blk.0.attn_v.weight", (n_embd, n_embd), normal(n_embd * n_embd)),
        ("blk.0.attn_output.weight", (n_embd, n_embd), normal(n_embd * n_embd)),
        ("blk.0.ffn_norm.weight", (n_embd,), array("f", [1.0] * n_embd)),
        ("blk.0.ffn_gate.weight", (n_embd, n_ff), normal(n_ff * n_embd)),
        ("blk.0.ffn_up.weight", (n_embd, n_ff), normal(n_ff * n_embd)),
        ("blk.0.ffn_down.weight", (n_ff, n_embd), normal(n_embd * n_ff)),
    ]

    header = b"GGUF" + struct.pack("<IQQ", 3, len(tensors), len(metadata))
    header += b"".join(_kv(k, v) for k, v in metadata.items())
    offset = 0
    infos = b""
    for name, dims, data in tensors:
        infos += _string(name) + struct.pack("<I", len(dims)) + struct.pack(f"<{len(dims)}Q", *dims)
        infos += struct.pack("<IQ", 0, offset)  # type F32, offset into the data section
        size = len(data) * 4
        offset += size + (-size % ALIGNMENT)
    blob = header + infos
    blob += b"\0" * (-len(blob) % ALIGNMENT)
    for _name, _dims, data in tensors:
        raw = data.tobytes()  # array('f') is native-endian; GGUF is little-endian (x86/ARM are LE)
        blob += raw + b"\0" * (-len(raw) % ALIGNMENT)
    path.write_bytes(blob)
    return path


if __name__ == "__main__":
    import sys

    print(write_tiny_llama(Path(sys.argv[1] if len(sys.argv) > 1 else "tiny.gguf")))
