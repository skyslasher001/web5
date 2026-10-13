"""Where things live on disk: `<vault>/<type>/<yyyy>/<mm>/<file>` plus the `.universe/` index (ADR-0003)."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from universe_vault.filetypes import FOLDERS, ItemType

INDEX_DIR = ".universe"
SIDECAR_SUFFIX = ".universe.json"
_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}
MAX_NAME = 150
HASH_CHUNK = 1024 * 1024


class VaultPathError(ValueError):
    pass


def slugify(text: str, *, max_len: int = 80) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    return slug[:max_len].strip("-") or "untitled"


def safe_filename(name: str) -> str:
    """A file name that is valid on Windows and everywhere else, keeping the original where possible."""
    name = unicodedata.normalize("NFC", name)
    name = _INVALID.sub("_", name).strip().rstrip(". ")
    stem, dot, ext = name.rpartition(".")
    if not dot:
        stem, ext = name, ""
    if stem.lower() in _RESERVED or not stem:
        stem = f"_{stem}"
    ext = ext[:16]
    stem = stem[: MAX_NAME - len(ext) - 1]
    return f"{stem}.{ext}" if ext else stem


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(HASH_CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True)
class Vault:
    root: Path

    @property
    def index(self) -> Path:
        return self.root / INDEX_DIR

    @property
    def db_path(self) -> Path:
        return self.index / "universe.db"

    @property
    def vectors(self) -> Path:
        return self.index / "vectors"

    @property
    def thumbs(self) -> Path:
        return self.index / "thumbs"

    @property
    def trash(self) -> Path:
        return self.index / "trash"

    @property
    def versions(self) -> Path:
        return self.index / "versions"

    @property
    def cache(self) -> Path:
        return self.index / "cache"

    def abs(self, rel: str) -> Path:
        """Resolve a stored relative path, refusing anything that escapes the vault."""
        path = (self.root / PurePosixPath(rel)).resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            raise VaultPathError(f"path escapes the vault: {rel}")
        return path

    def rel(self, path: Path) -> str:
        return path.resolve().relative_to(self.root.resolve()).as_posix()

    def contains(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.root.resolve())
        except ValueError:
            return False
        return True

    def in_index(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.index.resolve())
        except ValueError:
            return False
        return True

    def in_cache(self, path: Path) -> bool:
        try:
            path.resolve().relative_to(self.cache.resolve())
        except ValueError:
            return False
        return True

    def folder_for(self, item_type: ItemType, captured_at: str) -> Path:
        year, month = captured_at[0:4], captured_at[5:7]
        return self.root / FOLDERS[item_type] / year / month

    def free_path(self, folder: Path, name: str) -> Path:
        """`folder/name`, or `name (2).ext`, `name (3).ext`… if taken."""
        name = safe_filename(name)
        candidate = folder / name
        stem, ext = candidate.stem, candidate.suffix
        n = 2
        while candidate.exists() or candidate.with_name(candidate.name + SIDECAR_SUFFIX).exists():
            candidate = folder / f"{stem} ({n}){ext}"
            n += 1
        return candidate

    def thumb_path(self, item_id: str) -> Path:
        return self.thumbs / f"{item_id}.webp"

    def version_dir(self, item_id: str) -> Path:
        return self.versions / item_id

    def ensure(self) -> None:
        for path in (self.index, self.vectors, self.thumbs, self.trash, self.versions, self.cache):
            path.mkdir(parents=True, exist_ok=True)


def sidecar_path(original: Path) -> Path:
    return original.with_name(original.name + SIDECAR_SUFFIX)
