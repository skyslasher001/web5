"""The voice models UNIVERSE knows how to install, each pinned by size and SHA-256 (ADR-0016).

Core downloads them through the egress gate when you press Install (so offline mode and the kill switch block
it and the audit log records it); this module only verifies a downloaded file and puts it in place. A hash
mismatch fails closed: nothing is installed. Licences are per model — every one here is permissive.
"""

import hashlib
import shutil
import tarfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

Kind = Literal["stt", "tts", "vad"]


@dataclass(frozen=True)
class Download:
    url: str
    sha256: str
    size: int
    members: tuple[str, ...] = ()  # for a .tar.bz2: the files to keep (basename), everything else is skipped


@dataclass(frozen=True)
class VoiceModel:
    id: str
    kind: Kind
    title: str
    license: str
    source: str
    downloads: tuple[Download, ...]
    files: tuple[str, ...]  # what must exist in the model folder once installed

    @property
    def size(self) -> int:
        return sum(d.size for d in self.downloads)


_SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"
_KOKORO = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"

CATALOG: tuple[VoiceModel, ...] = (
    VoiceModel(
        id="whisper-tiny.en",
        kind="stt",
        title="Whisper tiny.en (fast, CPU-friendly)",
        license="MIT (OpenAI Whisper weights; ONNX export by k2-fsa/sherpa-onnx, Apache-2.0)",
        source="github.com/k2-fsa/sherpa-onnx",
        downloads=(
            Download(
                f"{_SHERPA}/sherpa-onnx-whisper-tiny.en.tar.bz2",
                "2bd6cf965c8bb3e068ef9fa2191387ee63a9dfa2a4e37582a8109641c20005dd",
                118_071_777,
                ("tiny.en-encoder.int8.onnx", "tiny.en-decoder.int8.onnx", "tiny.en-tokens.txt"),
            ),
        ),
        files=("tiny.en-encoder.int8.onnx", "tiny.en-decoder.int8.onnx", "tiny.en-tokens.txt"),
    ),
    VoiceModel(
        id="whisper-base.en",
        kind="stt",
        title="Whisper base.en (more accurate, still quick)",
        license="MIT (OpenAI Whisper weights; ONNX export by k2-fsa/sherpa-onnx, Apache-2.0)",
        source="github.com/k2-fsa/sherpa-onnx",
        downloads=(
            Download(
                f"{_SHERPA}/sherpa-onnx-whisper-base.en.tar.bz2",
                "475bc7052ce299c007f6d5d5407ba8601f819a2867f6eecee510ed17df581542",
                208_576_005,
                ("base.en-encoder.int8.onnx", "base.en-decoder.int8.onnx", "base.en-tokens.txt"),
            ),
        ),
        files=("base.en-encoder.int8.onnx", "base.en-decoder.int8.onnx", "base.en-tokens.txt"),
    ),
    VoiceModel(
        id="kokoro-82m",
        kind="tts",
        title="Kokoro-82M (int8) with 54 voices",
        license="Apache-2.0 (hexgrad/Kokoro-82M weights and voices)",
        source="github.com/thewh1teagle/kokoro-onnx",
        downloads=(
            Download(
                f"{_KOKORO}/kokoro-v1.0.int8.onnx",
                "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
                92_361_271,
            ),
            Download(
                f"{_KOKORO}/voices-v1.0.bin",
                "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
                28_214_398,
            ),
        ),
        files=("kokoro-v1.0.int8.onnx", "voices-v1.0.bin"),
    ),
    VoiceModel(
        id="silero-vad",
        kind="vad",
        title="Silero VAD (voice activity detection)",
        license="MIT (snakers4/silero-vad)",
        source="github.com/snakers4/silero-vad",
        downloads=(
            Download(
                "https://raw.githubusercontent.com/snakers4/silero-vad/master/src/silero_vad/data/silero_vad.onnx",
                "1a153a22f4509e292a94e67d6f9b85e8deb25b4988682b7e174c65279d8788e3",
                2_327_524,
            ),
        ),
        files=("silero_vad.onnx",),
    ),
)

BY_ID = {m.id: m for m in CATALOG}
DEFAULT_STT = "whisper-tiny.en"


class InstallError(Exception):
    pass


def folder(root: Path, model: VoiceModel) -> Path:
    return root / model.id


def installed(root: Path, model: VoiceModel) -> bool:
    return all((folder(root, model) / name).is_file() for name in model.files)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def place(root: Path, model: VoiceModel, download: Download, downloaded: Path) -> None:
    """Verify one downloaded file and move (or, for an archive, extract) it into the model's folder."""
    if downloaded.stat().st_size != download.size or sha256(downloaded) != download.sha256:
        raise InstallError(f"{model.id}: {Path(download.url).name} doesn't match its pinned SHA-256; not installed")
    target = folder(root, model)
    target.mkdir(parents=True, exist_ok=True)
    if not download.members:
        shutil.move(str(downloaded), target / Path(download.url).name)
        return
    wanted = set(download.members)
    with tarfile.open(downloaded, "r:bz2") as tar:
        for member in tar.getmembers():
            name = Path(member.name).name
            if name in wanted and member.isfile():
                member.name = name  # flatten; the 'data' filter still refuses links, devices and odd modes
                tar.extract(member, target, filter="data")
                wanted.discard(name)
    downloaded.unlink(missing_ok=True)
    if wanted:
        raise InstallError(f"{model.id}: the archive is missing {', '.join(sorted(wanted))}")
