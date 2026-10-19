"""Run the voice process: `python -m universe_voice` (started by Core only while the mic is on).

Environment: UNIVERSE_VOICE_PORT (loopback port; 0 = any free one), UNIVERSE_VOICE_PORT_FILE (where to write the
port once listening), UNIVERSE_VOICE_KEY (per-boot ticket key, hex),
UNIVERSE_VOICE_MODELS (the installed-models folder), UNIVERSE_VOICE_STT (which Whisper, default the best
installed), UNIVERSE_VOICE_WAKE (the wake phrase), UNIVERSE_VOICE_VOICE (default voice).
"""

import asyncio
import os
import sys
from collections.abc import Callable
from pathlib import Path

import uvicorn

from universe_common.log import register_secret
from universe_common.orphan import watch_parent
from universe_voice.models import BY_ID, CATALOG, DEFAULT_STT, folder, installed
from universe_voice.server import Engines, create_app
from universe_voice.vad import VAD, EnergyVAD, SileroVAD


def load_engines(root: Path, stt_id: str | None, wake: str, voice: str) -> Engines:
    from universe_voice.stt import WhisperOnnx
    from universe_voice.tts import KokoroTTS

    # Your pick, else tiny.en (fastest: the 1.5 s budget on a CPU), else whatever Whisper is installed.
    stt_models = [m for m in CATALOG if m.kind == "stt" and installed(root, m)]
    chosen = next((m for m in stt_models if m.id == (stt_id or DEFAULT_STT)), None)
    if chosen is None:
        chosen = next((m for m in stt_models if m.id == DEFAULT_STT), stt_models[0] if stt_models else None)
    stt = WhisperOnnx(folder(root, chosen)) if chosen else None
    kokoro = BY_ID["kokoro-82m"]
    tts = None
    if installed(root, kokoro):
        tts = KokoroTTS(folder(root, kokoro) / kokoro.files[0], folder(root, kokoro) / kokoro.files[1])
    silero = BY_ID["silero-vad"]
    silero_path = folder(root, silero) / silero.files[0]

    def vad() -> VAD:
        return SileroVAD(silero_path) if silero_path.is_file() else EnergyVAD()

    return Engines(stt=stt, tts=tts, vad=vad, default_voice=voice, wake_phrase=wake)


def main(load: Callable[[Path, str | None, str, str], Engines] = load_engines) -> int:
    key_hex = os.environ.get("UNIVERSE_VOICE_KEY", "")
    if len(key_hex) < 32:
        print("UNIVERSE_VOICE_KEY must be set (Core sets it)", file=sys.stderr)
        return 2
    register_secret(key_hex)
    root = Path(os.environ.get("UNIVERSE_VOICE_MODELS", "."))
    engines = load(
        root,
        os.environ.get("UNIVERSE_VOICE_STT"),
        os.environ.get("UNIVERSE_VOICE_WAKE", "hey universe"),
        os.environ.get("UNIVERSE_VOICE_VOICE", "af_heart"),
    )
    port = int(os.environ.get("UNIVERSE_VOICE_PORT", "0"))
    port_file = os.environ.get("UNIVERSE_VOICE_PORT_FILE")
    watch_parent(lambda: os._exit(0))  # never outlive Core
    config = uvicorn.Config(create_app(engines, bytes.fromhex(key_hex)), host="127.0.0.1", port=port)
    config.log_level = "warning"
    asyncio.run(_serve(uvicorn.Server(config), Path(port_file) if port_file else None, engines))
    return 0


async def _serve(server: uvicorn.Server, port_file: Path | None, engines: Engines) -> None:
    task = asyncio.create_task(server.serve())
    while not server.started:
        if task.done():
            task.result()  # startup failed: raise its error
            return
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    print(f"voice ready port={port} stt={engines.stt and engines.stt.name} tts={engines.tts and engines.tts.name}")
    sys.stdout.flush()
    if port_file is not None:
        tmp = port_file.with_suffix(".tmp")
        tmp.write_text(str(port), encoding="utf-8")
        os.replace(tmp, port_file)
    await task


if __name__ == "__main__":
    sys.exit(main())
