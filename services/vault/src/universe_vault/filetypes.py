"""Item types: detection from file names, and the vault folder each type lives in (ARCHITECTURE.md §4.5)."""

import mimetypes
import re
from pathlib import PurePath
from typing import Literal

ItemType = Literal[
    "note",
    "idea",
    "song",
    "audio",
    "voice_memo",
    "photo",
    "video",
    "document",
    "pdf",
    "spreadsheet",
    "code_repo",
    "code_file",
    "link",
    "screenshot",
    "transcript",
    "folder",
    "file",
]

ITEM_TYPES: tuple[ItemType, ...] = (
    "note",
    "idea",
    "song",
    "audio",
    "voice_memo",
    "photo",
    "video",
    "document",
    "pdf",
    "spreadsheet",
    "code_repo",
    "code_file",
    "link",
    "screenshot",
    "transcript",
    "folder",
    "file",
)

FOLDERS: dict[ItemType, str] = {
    "note": "notes",
    "idea": "ideas",
    "song": "songs",
    "audio": "audio",
    "voice_memo": "voice-memos",
    "photo": "photos",
    "video": "videos",
    "document": "documents",
    "pdf": "pdfs",
    "spreadsheet": "spreadsheets",
    "code_repo": "code",
    "code_file": "code",
    "link": "links",
    "screenshot": "screenshots",
    "transcript": "transcripts",
    "folder": "folders",
    "file": "files",
}

# fmt: off
_CODE_EXTENSIONS = {
    ".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".java", ".c", ".h", ".cpp", ".hpp", ".cc", ".cs", ".go",
    ".rs", ".rb", ".php", ".swift", ".kt", ".kts", ".sh", ".bash", ".ps1", ".psm1", ".bat", ".cmd", ".sql", ".json",
    ".jsonc", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".css", ".scss", ".less", ".lua", ".r", ".vue", ".svelte",
    ".dart", ".zig", ".m", ".pl", ".ex", ".exs", ".hs", ".scala", ".ipynb", ".xml", ".graphql", ".proto",
    ".dockerfile",
}
# fmt: on

_EXTENSIONS: dict[ItemType, set[str]] = {
    "note": {".md", ".markdown"},
    "document": {".txt", ".rtf", ".docx", ".odt", ".html", ".htm", ".pptx", ".log"},
    "pdf": {".pdf"},
    "spreadsheet": {".xlsx", ".xlsm", ".csv", ".tsv", ".ods"},
    "photo": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".heif", ".bmp", ".tif", ".tiff"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wma", ".aiff", ".aif"},
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v", ".wmv"},
    "code_file": _CODE_EXTENSIONS,
    "link": {".url", ".webloc"},
}
_BY_EXTENSION: dict[str, ItemType] = {ext: kind for kind, exts in _EXTENSIONS.items() for ext in exts}
_SPECIAL_NAMES: dict[str, ItemType] = {
    "dockerfile": "code_file",
    "makefile": "code_file",
    "readme": "document",
    "license": "document",
}
_SCREENSHOT = re.compile(r"(screen ?shot|screen_shot|screenshot|screen capture|snip|^scr_)", re.IGNORECASE)

# Types whose bytes are (mostly) text we can read directly.
PLAIN_TEXT_EXTENSIONS = (
    _EXTENSIONS["note"] | _EXTENSIONS["code_file"] | {".txt", ".log", ".csv", ".tsv", ".html", ".htm"}
) - {".ipynb"}
IMAGE_TYPES: frozenset[str] = frozenset({"photo", "screenshot"})
TEXT_TYPES: frozenset[str] = frozenset(
    {"note", "idea", "document", "pdf", "spreadsheet", "code_file", "link", "transcript", "file"}
)
TIME_BASED_TYPES: frozenset[str] = frozenset({"audio", "song", "voice_memo", "video"})


def detect_type(name: str) -> ItemType:
    path = PurePath(name)
    ext = path.suffix.lower()
    kind: ItemType | None = _BY_EXTENSION.get(ext)
    if kind is None and not ext:
        kind = _SPECIAL_NAMES.get(path.name.lower())
    if kind == "photo" and _SCREENSHOT.search(path.stem):
        return "screenshot"
    return kind or "file"


def guess_mime(name: str) -> str | None:
    mime, _ = mimetypes.guess_type(name, strict=False)
    if mime is None and PurePath(name).suffix.lower() in {".md", ".markdown"}:
        return "text/markdown"
    return mime
