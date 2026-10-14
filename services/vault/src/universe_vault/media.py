"""Image work for the pipeline: thumbnails (Pillow) and OCR (RapidOCR, offline PP-OCR models)."""

import logging
import os
import threading
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

THUMB_SIZE = 512
OCR_MAX_SIDE = 1600  # ~190 dpi for a letter page: enough to read, and detection cost grows with pixels
OCR_MIN_SIDE = 32
OCR_MIN_SCORE = 0.5


def make_thumbnail(src: Path, dest: Path) -> bool:
    try:
        with Image.open(src) as img:
            img = ImageOps.exif_transpose(img)
            img.thumbnail((THUMB_SIZE, THUMB_SIZE))
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".tmp")
            img.save(tmp, "WEBP", quality=80, method=4)
            os.replace(tmp, dest)
            return True
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return False


class OcrEngine:
    """RapidOCR, created on first use (≈3 s) and reused. Its models ship inside the wheel: no download."""

    def __init__(self) -> None:
        self._engine: Any = None
        self._lock = threading.Lock()

    def _get(self) -> Any:
        with self._lock:
            if self._engine is None:
                logging.getLogger("RapidOCR").setLevel(logging.WARNING)
                from rapidocr import RapidOCR

                self._engine = RapidOCR()
            return self._engine

    def __call__(self, path: Path) -> str:
        import numpy as np

        try:
            with Image.open(path) as img:
                img = ImageOps.exif_transpose(img).convert("RGB")
                if min(img.size) < OCR_MIN_SIDE:
                    return ""
                img.thumbnail((OCR_MAX_SIDE, OCR_MAX_SIDE))
                pixels = np.asarray(img)[:, :, ::-1].copy()  # RGB → BGR, as OpenCV expects
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
            return ""
        # No orientation classifier: EXIF rotation is already applied and screenshots and scans are upright;
        # it cost ~40% of OCR time for nothing (measured 2026-10-13).
        result = self._get()(pixels, use_cls=False)
        texts = getattr(result, "txts", None) or ()
        scores = getattr(result, "scores", None) or ()
        return "\n".join(t for t, s in zip(texts, scores, strict=False) if t and s >= OCR_MIN_SCORE)
