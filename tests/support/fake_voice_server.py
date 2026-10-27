"""The voice process with stand-in engines: `python -m tests.support.fake_voice_server` (same env contract as
`python -m universe_voice`). Core's voice tests run it so they exercise the real spawn, port file, tickets,
WebSocket and kill switch without downloading models. UNIVERSE_FAKE_STT_LINES ("|"-separated) is what it hears."""

import os
import sys
from pathlib import Path

from tests.support.fake_voice import FakeSTT, FakeTTS
from universe_voice.__main__ import main
from universe_voice.server import Engines
from universe_voice.vad import EnergyVAD


def fake_engines(_root: Path, _stt: str | None, wake: str, voice: str) -> Engines:
    lines = [line for line in os.environ.get("UNIVERSE_FAKE_STT_LINES", "").split("|") if line]
    return Engines(stt=FakeSTT(lines), tts=FakeTTS(), vad=EnergyVAD, default_voice=voice, wake_phrase=wake)


if __name__ == "__main__":
    sys.exit(main(load=fake_engines))
