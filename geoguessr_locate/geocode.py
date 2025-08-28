from __future__ import annotations

import os
import math
import time
from dataclasses import dataclass
from typing import Optional, List

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


@dataclass
class SearchPlace:
    lat: float
    lon: float
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


def _deg_box(lat: float, lon: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return a (min_lon, min_lat, max_lon, max_lat) viewbox around a point."""
    dlat = radius_km / 111.0
    dlon = radius_km / max(1e-6, (111.0 * abs(math.cos(math.radians(lat)))))
    return (lon - dlon, lat - dlat, lon + dlon, lat + dlat)


def forward_geocode(
    query: str,
    *,
    countrycodes: Optional[str] = None,
    bias: Optional[tuple[float, float]] = None,
    viewbox_km: Optional[float] = None,
    limit: int = 5,
    cache: Optional[Cache] = None,
) -> List[SearchPlace]:
    """Search Nominatim for a textual place. Returns list of candidates.

    - countrycodes: comma-separated alpha-2 lower-case (e.g. "us,gb").
    - bias + viewbox_km: restrict search to a viewbox around bias point if provided.
    """
    cache = cache or Cache()
    vb = None
    if bias and viewbox_km and viewbox_km > 0:
        vb = _deg_box(bias[0], bias[1], viewbox_km)

    # Build cache key
    cc_key = countrycodes or ""
    vb_key = f"_{round(vb[0],3)}_{round(vb[1],3)}_{round(vb[2],3)}_{round(vb[3],3)}" if vb else ""
    key = f"nominatim_search_{hash((query.strip().lower(), cc_key, vb_key, limit))}"
    cached = cache.get(key)
    if cached is not None:
        try:
            return [SearchPlace(**item) for item in cached]
        except Exception:
            pass

    _rate_limit_gate(cache)

    params = {
        "q": query,
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(1, min(10, limit)),
    }
    if countrycodes:
        params["countrycodes"] = countrycodes.lower()
    if vb:
        # viewbox: left,top,right,bottom (lon,lat,lon,lat)
        left, bottom, right, top = vb[0], vb[1], vb[2], vb[3]
        params["viewbox"] = f"{left},{top},{right},{bottom}"
        params["bounded"] = 1

    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/search",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
        results: List[SearchPlace] = []
        for item in data:
            addr = item.get("address", {})
            try:
                lat = float(item.get("lat"))
                lon = float(item.get("lon"))
            except Exception:
                continue
            results.append(
                SearchPlace(
                    lat=lat,
                    lon=lon,
                    country=addr.get("country"),
                    state=addr.get("state") or addr.get("region"),
                    county=addr.get("county"),
                    city=addr.get("city") or addr.get("town") or addr.get("village"),
                    display_name=item.get("display_name"),
                )
            )
        # Cache a simple serializable representation
        cache.set(key, [sp.__dict__ for sp in results])
        return results
    except Exception:
        return []

