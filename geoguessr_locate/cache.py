from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from filelock import FileLock

from .utils import get_cache_dir


class Cache:
    def __init__(self, cache_dir: Optional[Path] = None) -> None:
        self.root = cache_dir or get_cache_dir()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.root / f"{key}.json"

    def get(self, key: str) -> Optional[Any]:
        p = self._path(key)
        if not p.exists():
            return None
        try:
            with p.open("r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return None

    def set(self, key: str, value: Any) -> None:
        p = self._path(key)
        lock = FileLock(str(p) + ".lock")
        with lock:
            with p.open("w", encoding="utf-8") as f:
                json.dump(value, f, ensure_ascii=False, indent=2)

    def clear(self) -> None:
        for item in self.root.glob("*.json"):
            try:
                item.unlink()
            except Exception:
                pass

