"""Structured error capture: normalized stack, stable fingerprint for grouping (Forge input)."""

import hashlib
import re
import traceback
from dataclasses import dataclass, field
from typing import Any

MAX_MESSAGE = 2_000
MAX_STACK = 20_000

_HEX_OR_NUM = re.compile(r"0x[0-9a-fA-F]+|\b\d+\b")


@dataclass(frozen=True)
class CapturedError:
    kind: str
    message: str
    stack: str
    fingerprint: str
    context: dict[str, Any] = field(default_factory=dict)


def fingerprint(kind: str, frames: list[str]) -> str:
    """Same error type at the same code locations groups together, even if messages differ."""
    basis = kind + "\n" + "\n".join(frames[-8:])
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:16]


def _frames_from_exception(exc: BaseException) -> list[str]:
    frames = []
    for frame in traceback.extract_tb(exc.__traceback__):
        filename = frame.filename.replace("\\", "/").rsplit("/site-packages/", 1)[-1]
        filename = filename.rsplit("/src/", 1)[-1]
        frames.append(f"{filename}:{frame.name}")
    return frames


def capture_exception(exc: BaseException, context: dict[str, Any] | None = None) -> CapturedError:
    kind = f"{type(exc).__module__}.{type(exc).__qualname__}".removeprefix("builtins.")
    stack = "".join(traceback.format_exception(exc))
    return CapturedError(
        kind=kind,
        message=str(exc)[:MAX_MESSAGE],
        stack=stack[-MAX_STACK:],
        fingerprint=fingerprint(kind, _frames_from_exception(exc)),
        context=context or {},
    )


def fingerprint_from_text(kind: str, message: str, stack: str) -> str:
    """Fingerprint for errors reported as text (renderer, Electron main): strip volatile numbers."""
    lines = [line.strip() for line in stack.splitlines() if line.strip().startswith("at ")]
    frames = [_HEX_OR_NUM.sub("#", line) for line in lines] or [_HEX_OR_NUM.sub("#", message)[:200]]
    return fingerprint(kind, frames)
