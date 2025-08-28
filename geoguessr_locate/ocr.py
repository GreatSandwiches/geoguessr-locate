from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import pytesseract  # type: ignore
    from PIL import Image
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None  # type: ignore
    Image = None  # type: ignore


def extract_ocr_text(image_path: str | Path, max_chars: int = 2000) -> Optional[str]:
    """Best-effort OCR on the image. Returns a trimmed text blob or None.

    This is optional and succeeds only if Pillow + pytesseract are installed
    and Tesseract is available on the system PATH. The function is conservative
    and returns None on any issue to keep the main pipeline robust.
    """
    if pytesseract is None or Image is None:
        return None
    try:
        p = Path(image_path)
        if not p.exists():
            return None
        with Image.open(p) as im:
            rgb = im.convert("RGB")
            text = pytesseract.image_to_string(rgb)
            text = (text or "").strip()
            if not text:
                return None
            # Collapse excessive whitespace and limit size to avoid bloating prompts
            text = " ".join(text.split())
            if len(text) > max_chars:
                text = text[:max_chars]
            return text
    except Exception:
        return None

