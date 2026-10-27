"""Metadata extraction: file properties, EXIF (Pillow), audio tags (tinytag), note frontmatter."""

import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from PIL import ExifTags, Image, UnidentifiedImageError
from tinytag import TinyTag, TinyTagException

from universe_vault.filetypes import IMAGE_TYPES, TIME_BASED_TYPES

_FRONTMATTER = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_HEADING = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$", re.MULTILINE)
_EXIF_DATE = re.compile(r"^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2}):(\d{2})")
Image.MAX_IMAGE_PIXELS = 200_000_000  # refuse decompression bombs beyond ~200 MP


def iso_utc(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def file_time(path: Path) -> str:
    return iso_utc(path.stat().st_mtime)


def _exif_local_to_utc(value: str) -> str | None:
    """EXIF dates have no zone; they're the camera's local time, so assume this PC's zone."""
    match = _EXIF_DATE.match(value.strip())
    if not match:
        return None
    year, month, day, hour, minute, second = (int(p) for p in match.groups())
    if year < 1971:
        return None
    try:
        ts = time.mktime((year, month, day, hour, minute, second, 0, 0, -1))
    except (OverflowError, ValueError):
        return None
    return iso_utc(ts)


def _gps(gps: dict[int, Any]) -> tuple[float, float] | None:
    def deg(values: Any, ref: Any) -> float:
        d, m, s = (float(v) for v in values)
        value = d + m / 60 + s / 3600
        return -value if ref in ("S", "W", b"S", b"W") else value

    try:
        return deg(gps[2], gps.get(1)), deg(gps[4], gps.get(3))
    except (KeyError, TypeError, ValueError, ZeroDivisionError):
        return None


def image_metadata(path: Path) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        with Image.open(path) as img:
            out["width"], out["height"] = img.size
            out["format"] = img.format
            exif = img.getexif()
            if exif:
                base = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
                sub = exif.get_ifd(ExifTags.IFD.Exif) if hasattr(ExifTags, "IFD") else {}
                tags = {**base, **{ExifTags.TAGS.get(k, str(k)): v for k, v in sub.items()}}
                taken = tags.get("DateTimeOriginal") or tags.get("DateTime")
                if isinstance(taken, str) and (when := _exif_local_to_utc(taken)):
                    out["taken_at"] = when
                camera = " ".join(str(tags[k]).strip() for k in ("Make", "Model") if tags.get(k))
                if camera:
                    out["camera"] = camera
                if tags.get("LensModel"):
                    out["lens"] = str(tags["LensModel"]).strip()
                gps_ifd = exif.get_ifd(ExifTags.IFD.GPSInfo) if hasattr(ExifTags, "IFD") else {}
                if gps_ifd and (coords := _gps(dict(gps_ifd))):
                    out["lat"], out["lon"] = round(coords[0], 6), round(coords[1], 6)
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        out["image_error"] = f"{type(exc).__name__}: {exc}"[:300]
    return out


def audio_metadata(path: Path) -> dict[str, Any]:
    try:
        tag = TinyTag.get(str(path))
    except (TinyTagException, OSError, ValueError) as exc:
        return {"tag_error": f"{type(exc).__name__}: {exc}"[:300]}
    out: dict[str, Any] = {}
    for key in ("title", "artist", "album", "albumartist", "composer", "genre", "year", "comment"):
        value = getattr(tag, key, None)
        if value not in (None, ""):
            out[key] = str(value).strip()
    for key in ("duration", "bitrate", "samplerate", "channels"):
        value = getattr(tag, key, None)
        if value:
            out[key] = round(float(value), 3) if key == "duration" else value
    return out


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    match = _FRONTMATTER.match(text)
    if not match:
        return {}, text
    try:
        data = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return {}, text
    return (data if isinstance(data, dict) else {}), text[match.end() :]


def note_title(text: str, fallback: str) -> str:
    front, body = parse_frontmatter(text)
    title = front.get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()[:300]
    heading = _HEADING.search(body)
    if heading:
        return heading.group(1).strip()[:300]
    return fallback


def captured_at(path: Path, item_type: str) -> str:
    """When the thing happened: EXIF capture time for photos, otherwise the file's modified time."""
    if item_type in IMAGE_TYPES:
        taken = image_metadata(path).get("taken_at")
        if taken:
            return taken
    return file_time(path)


def extract(path: Path, item_type: str) -> dict[str, Any]:
    stat = path.stat()
    meta: dict[str, Any] = {"file_name": path.name, "file_modified": iso_utc(stat.st_mtime)}
    if item_type in IMAGE_TYPES:
        meta.update(image_metadata(path))
    elif item_type in TIME_BASED_TYPES:
        meta.update(audio_metadata(path))
    return meta
