from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Optional

import requests

from .cache import Cache


NOMINATIM_BASE = "https://nominatim.openstreetmap.org/reverse"
USER_AGENT = os.environ.get(
    "GEOGUESSR_LOCATE_UA",
    "geoguessr-locate/0.1 (+https://example.com; contact: local)",
)


@dataclass
class Place:
    country: Optional[str]
    state: Optional[str]
    county: Optional[str]
    city: Optional[str]
    display_name: Optional[str]


def _rate_limit_gate(cache: Cache) -> None:
    # simple 1 req/sec limiter using a timestamp file
    ts_path = cache.root / "nominatim.last"
    last = 0.0
    if ts_path.exists():
        try:
            last = float(ts_path.read_text().strip() or "0")
        except Exception:
            last = 0.0
    now = time.time()
    elapsed = now - last
    if elapsed < 1.0:
        time.sleep(1.0 - elapsed)
    ts_path.write_text(str(time.time()))


def reverse_geocode(lat: float, lon: float, cache: Optional[Cache] = None) -> Place | None:
    cache = cache or Cache()
    key = f"nominatim_{round(lat, 3)}_{round(lon, 3)}"
    cached = cache.get(key)
    if cached is not None:
        return Place(**cached)

    _rate_limit_gate(cache)

    try:
        resp = requests.get(
            NOMINATIM_BASE,
            params={
                "lat": lat,
                "lon": lon,
                "format": "jsonv2",
                "zoom": 10,
                "addressdetails": 1,
            },
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        addr = data.get("address", {})
        place = Place(
            country=addr.get("country"),
            state=addr.get("state") or addr.get("region"),
            county=addr.get("county"),
            city=addr.get("city") or addr.get("town") or addr.get("village"),
            display_name=data.get("display_name"),
        )
        cache.set(key, place.__dict__)
        return place
    except Exception:
        return None

