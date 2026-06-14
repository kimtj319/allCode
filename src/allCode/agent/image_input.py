"""Encode local image files into data URLs for multimodal model input."""

from __future__ import annotations

import base64
from pathlib import Path

_MIME_BY_SUFFIX = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".bmp": "image/bmp",
}

MAX_IMAGE_BYTES = 8 * 1024 * 1024


def is_image_path(path: str) -> bool:
    return Path(path).suffix.lower() in _MIME_BY_SUFFIX


def encode_image_file(path: str | Path) -> str | None:
    """Return a ``data:<mime>;base64,...`` URL for an image file, or None.

    None is returned for missing files, unsupported types, or files over the
    size cap, so callers can skip silently rather than fail a turn.
    """
    file_path = Path(path).expanduser()
    mime = _MIME_BY_SUFFIX.get(file_path.suffix.lower())
    if mime is None or not file_path.is_file():
        return None
    try:
        if file_path.stat().st_size > MAX_IMAGE_BYTES:
            return None
        raw = file_path.read_bytes()
    except OSError:
        return None
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def encode_image_files(paths: list[str]) -> list[str]:
    return [url for path in paths if (url := encode_image_file(path)) is not None]
