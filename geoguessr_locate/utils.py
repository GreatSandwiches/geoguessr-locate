from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
from typing import Optional

from PIL import Image


ALLOWED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}


def ensure_image_path(path: str | os.PathLike[str]) -> Path:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Image not found: {p}")
    if p.suffix.lower() not in ALLOWED_EXTS:
        raise ValueError(f"Unsupported image type {p.suffix}. Supported: {sorted(ALLOWED_EXTS)}")
    return p


def load_image_bytes(path: str | os.PathLike[str]) -> bytes:
    p = ensure_image_path(path)
    with Image.open(p) as im:
        # Convert to RGB to avoid weird formats, strip EXIF
        rgb = im.convert("RGB")
        buf = io.BytesIO()
        rgb.save(buf, format="JPEG", quality=92)
        return buf.getvalue()


def sha256_file(path: str | os.PathLike[str]) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def b64_data_url_jpeg(image_bytes: bytes) -> str:
    b64 = base64.b64encode(image_bytes).decode("ascii")
    return f"data:image/jpeg;base64,{b64}"


def get_cache_dir() -> Path:
    env = os.environ.get("GEOGUESSR_LOCATE_CACHE")
    if env:
        d = Path(env)
    else:
        d = Path.home() / ".cache" / "geoguessr-locate"
    d.mkdir(parents=True, exist_ok=True)
    return d

