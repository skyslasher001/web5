"""The `transcribe` stage's engine: Whisper (ONNX) from the installed voice models (ADR-0016).

Created on first use and reused. Until a Whisper model is installed the stage is skipped with that reason, and
installing one requeues those items (`requeue_untranscribed`).
"""

import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from universe_vault.pipeline import StageSkipped

NO_STT = "No speech-to-text model installed (Voice → Models → Install Whisper)"
# For recordings accuracy beats speed: prefer base.en when it's installed (live voice prefers tiny.en).
PREFERRED = ("whisper-base.en", "whisper-tiny.en")


class Transcriber:
    def __init__(self, models_root: Path, engines: Callable[[], tuple[Any, Any]] | None = None) -> None:
        self.root = models_root
        self._engines_override = engines  # tests: stand-in (STT, VAD); everything else is the real path
        self._stt: Any = None
        self._vad_path: Path | None = None
        self._lock = threading.Lock()

    def _engines(self) -> tuple[Any, Any]:
        if self._engines_override is not None:
            return self._engines_override()
        from universe_voice.models import BY_ID, folder, installed
        from universe_voice.vad import EnergyVAD, SileroVAD

        with self._lock:
            if self._stt is None:
                chosen = next((BY_ID[i] for i in PREFERRED if installed(self.root, BY_ID[i])), None)
                if chosen is None:
                    raise StageSkipped(NO_STT)
                from universe_voice.stt import WhisperOnnx

                self._stt = WhisperOnnx(folder(self.root, chosen))
                silero = BY_ID["silero-vad"]
                path = folder(self.root, silero) / silero.files[0]
                self._vad_path = path if path.is_file() else None
            vad = SileroVAD(self._vad_path) if self._vad_path else EnergyVAD()
            return self._stt, vad

    @property
    def model(self) -> str | None:
        return self._stt.name if self._stt is not None else None

    def __call__(self, path: Path) -> list[Any]:
        from universe_voice import longform

        stt, vad = self._engines()
        try:
            audio = longform.load_audio(path)
        except longform.Undecodable as exc:
            raise StageSkipped(str(exc)) from exc
        return longform.transcribe(audio, stt, vad)
