from __future__ import annotations

from typing import List, Optional, Tuple
from math import radians, cos, sin, asin, sqrt

from .types import ModelOutput, Candidate, FinalResult, Cues
from .geocode import reverse_geocode, forward_geocode


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great circle distance between two points in kilometers."""
    R = 6371  # Earth's radius in kilometers
    
    lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    
    a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
    c = 2 * asin(sqrt(a))
    return R * c

def calculate_cue_score(cues: Optional[Cues]) -> float:
    """Calculate a score (0-1) based on the completeness and specificity of visual cues."""
    if not cues:
        return 0.0
        
    score = 0.0
    total_weight = 0.0
    
    # Language identification (high weight as it's a strong regional indicator)
    if cues.languages_seen:
        score += len(cues.languages_seen) * 0.15
        total_weight += 0.15 * 3  # Assuming max 3 languages is highly confident
    
    # Driving side (strong binary indicator)
    if cues.driving_side:
        score += 0.1
        total_weight += 0.1
    
    # Road infrastructure (very reliable for region identification)
    if cues.road_markings:
        score += 0.15
        total_weight += 0.15
    if cues.signage_features:
        score += 0.15
        total_weight += 0.15
    
    # Environmental cues (good for region verification)
    if cues.vegetation_climate:
        score += 0.1
        total_weight += 0.1
    
    # Infrastructure (helps narrow down development level and region)
    if cues.electrical_infrastructure:
        score += 0.1
        total_weight += 0.1
    
    # Additional cues
    if cues.other_cues:
        score += 0.05
        total_weight += 0.05
    
    # Normalize score
    return score / total_weight if total_weight > 0 else 0.0

def refine_confidence(candidate: Candidate) -> float:
    """Calculate a refined confidence score based on multiple factors."""
    base_confidence = candidate.confidence if candidate.confidence is not None else 0.0
    
    # Factor in the quality and quantity of visual cues
    cue_score = calculate_cue_score(candidate.cues)
    
    # Consider the specificity of location data
    location_score = 0.0
    location_weight = 0.0
    
    if candidate.country_code:
        location_score += 0.2
        location_weight += 0.2
    if candidate.admin1:
        location_score += 0.3
        location_weight += 0.3
    if candidate.admin2:
        location_score += 0.2
        location_weight += 0.2
    if candidate.nearest_city:
        location_score += 0.3
        location_weight += 0.3
    
    location_score = location_score / location_weight if location_weight > 0 else 0.0
    
    # Calculate final confidence as weighted average
    final_confidence = (
        base_confidence * 0.4 +  # Original model confidence
        cue_score * 0.3 +        # Quality of visual cues
        location_score * 0.3     # Specificity of location data
    )
    
    return min(1.0, final_confidence)


# Countries that predominantly drive on the left (ISO-3166 alpha-2)
# Expanded for better contradiction checks
LEFT_DRIVING = {
    # Europe
    "GB", "IE", "CY", "MT",
    # Oceania / Pacific
    "AU", "NZ", "FJ", "PG", "SB", "TL",
    # Asia
    "JP", "TH", "ID", "LK", "SG", "MY", "IN", "BD", "PK", "NP", "BN", "HK", "MO",
    # Africa
    "ZA", "KE", "UG", "TZ", "BW", "NA", "ZM", "ZW", "LS", "SZ", "MU",
    # Americas / Caribbean
    "GY", "SR", "TT", "JM", "BB", "BS", "BM", "KY", "AG", "DM", "GD", "LC", "VC", "TC", "VG",
}

# Countries using MPH on road signs (best-effort, not exhaustive)
# Split by driving side because it helps disambiguate US vs GB and others
MPH_RIGHT = {
    "US",  # United States and territories
    "BZ",  # Belize
    "LR",  # Liberia
    # US territories commonly show MPH and drive on right
    "GU", "PR"
}
MPH_LEFT = {
    "GB", "BS", "BB", "BM", "KY", "JM", "TT", "AG", "DM", "GD", "LC", "VC", "TC", "VG"
}
MPH_ALL = MPH_RIGHT | MPH_LEFT


def _expected_driving_side(country_code: str | None) -> str | None:
    if not country_code:
        return None
    cc = country_code.upper()
    if cc in LEFT_DRIVING:
        return "left"
    # default assumption if known but not left: right
    if len(cc) == 2:
        return "right"
    return None


def contradiction_penalty(candidate: Candidate) -> float:
    """Return a small penalty for contradictions in cues vs country.

    Currently: driving side mismatch.
    """
    try:
        side = candidate.cues.driving_side if candidate.cues else None
    except Exception:
        side = None
    expected = _expected_driving_side(candidate.country_code)
    if side and expected and side != expected:
        return 0.08  # modest penalty
    return 0.0


def _units_from_text(txt: Optional[str]) -> tuple[bool, bool]:
    """Detect presence of MPH or KM/H tokens in free text.

    Returns (mph_present, kmh_present).
    """
    if not txt:
        return (False, False)
    t = txt.lower().replace(" ", "")
    mph = ("mph" in t) or ("mi/h" in t) or ("milesperhour" in t)
    kmh = ("km/h" in t) or ("kmh" in t) or ("kph" in t) or ("kilometersperhour" in t)
    return (mph, kmh)


def speed_units_adjustment(candidate: Candidate) -> float:
    """Adjust confidence based on detected speed units vs candidate country.

    Small boost when consistent, small penalty when contradictory. Conservative magnitudes.
    """
    cues = candidate.cues
    if not cues:
        return 0.0
    pieces = [
        cues.signage_features or "",
        cues.other_cues or "",
        cues.road_markings or "",
    ]
    mph, kmh = False, False
    for p in pieces:
        m, k = _units_from_text(p)
        mph = mph or m
        kmh = kmh or k
    if not mph and not kmh:
        return 0.0

    cc = (candidate.country_code or "").upper()
    side = (cues.driving_side or "").lower() if cues.driving_side else None

    boost = 0.0
    if mph:
        # MPH expected countries
        if (cc in MPH_RIGHT and (not side or side == "right")) or (cc in MPH_LEFT and (not side or side == "left")):
            boost += 0.05
        # Discourage unlikely MPH countries
        elif cc and (cc not in MPH_ALL):
            boost -= 0.04

    if kmh:
        # Penalize explicitly MPH-only strongholds if KM/H appears
        if cc in {"US"}:
            boost -= 0.05
        # Mild boost otherwise (most of the world uses km/h)
        elif cc and cc not in MPH_RIGHT:
            boost += 0.02
    return boost


def radius_adjustment(candidate: Candidate) -> float:
    """Adjust confidence based on confidence_radius_km: tighter radius -> more trust."""
    r = candidate.confidence_radius_km
    if r is None:
        return 0.0
    if r <= 10:
        return 0.05
    if r <= 30:
        return 0.03
    if r <= 80:
        return 0.01
    if r >= 500:
        return -0.05
    if r >= 200:
        return -0.02
    return 0.0


def _normalize(s: Optional[str]) -> Optional[str]:
    return s.strip().lower() if isinstance(s, str) else None


def _geocode_consistency_adjust(candidate: Candidate) -> float:
    """Reverse geocode the candidate's lat/lon and compute a small adjustment.

    Also fills missing admin/city fields when possible. Returns a boost (or penalty).
    """
    if candidate.latitude is None or candidate.longitude is None:
        return 0.0
    place = reverse_geocode(candidate.latitude, candidate.longitude)
    if not place:
        return 0.0

    # Fill missing fields conservatively
    if not candidate.country_name and place.country:
        candidate.country_name = place.country
    if not candidate.admin1 and place.state:
        candidate.admin1 = place.state
    if not candidate.admin2 and place.county:
        candidate.admin2 = place.county
    if not candidate.nearest_city and place.city:
        candidate.nearest_city = place.city

    boost = 0.0
    # Compare normalized strings where present
    if candidate.country_name and place.country:
        if _normalize(candidate.country_name) == _normalize(place.country):
            boost += 0.04
        else:
            boost -= 0.06
    if candidate.admin1 and place.state:
        if _normalize(candidate.admin1) == _normalize(place.state):
            boost += 0.02
        # only penalize if country also matched to avoid double-counting uncertain regions
        elif candidate.country_name and place.country and _normalize(candidate.country_name) == _normalize(place.country):
            boost -= 0.02
    return boost


def _cluster_adjustments(candidates: list[Candidate]) -> dict[int, float]:
    """Compute small boosts for candidates that cluster geographically.

    Returns mapping from index to adjustment value.
    """
    coords: list[tuple[int, Candidate]] = [
        (i, c) for i, c in enumerate(candidates) if c.latitude is not None and c.longitude is not None
    ]
    n = len(coords)
    if n < 2:
        return {}
    # Precompute pairwise neighbor counts within 150 km
    neighbors = {i: 0 for i, _ in coords}
    for a in range(n):
        ia, ca = coords[a]
        for b in range(a + 1, n):
            ib, cb = coords[b]
            d = haversine_distance(ca.latitude or 0.0, ca.longitude or 0.0, cb.latitude or 0.0, cb.longitude or 0.0)
            if d <= 150.0:
                neighbors[ia] += 1
                neighbors[ib] += 1
    adj: dict[int, float] = {}
    for i, _c in coords:
        k = neighbors.get(i, 0)
        if k >= 2:
            adj[i] = 0.04
        elif k == 1:
            adj[i] = 0.02
        else:
            adj[i] = -0.01  # lightly discourage isolated outliers when others cluster
    return adj


def _extract_poi_queries(candidate: Candidate, max_queries: int = 5) -> list[str]:
    """Extract potential POI/place/road queries from candidate textual fields.

    Heuristic: look into reasons and cues for road numbers (I-95, A3, E75, BR-101)
    and multi-word capitalized phrases likely to be place or street names.
    """
    texts: list[str] = []
    if candidate.reasons:
        texts.append(candidate.reasons)
    cues = candidate.cues
    if cues:
        for t in [cues.signage_features, cues.other_cues, cues.road_markings]:
            if t:
                texts.append(t)
    blob = "; ".join(texts)
    if not blob:
        return []

    import re

    # Road tokens
    road_pattern = re.compile(r"\b((?:I|US|BR|SP|RN|A|M|N|D|E|R|CR|RN|MX|CA|UK|NZ|ZA|IN|JP|TH|ID)[- ]?\d{1,4})\b", re.I)
    roads = set(m.group(1).strip() for m in road_pattern.finditer(blob))

    # Place-like tokens: sequences of capitalized words (allow accents), length >= 2 words
    # Keep common street words to improve search (Rue, Rua, Calle, Av., Avenue, Road)
    place_pattern = re.compile(r"\b([A-ZÀ-ÿ][\wÀ-ÿ'’.-]+(?:\s+[A-ZÀ-ÿ][\wÀ-ÿ'’.-]+)+)\b")
    places_raw = [m.group(1).strip() for m in place_pattern.finditer(blob)]
    # Filter out overly generic phrases
    bad = {"Speed Limit", "No Parking", "City Center", "One Way", "Exit Only"}
    places = [p for p in places_raw if p not in bad and len(p) <= 60]

    # Deduplicate preserving order
    seen = set()
    queries: list[str] = []
    for item in list(roads) + places:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(item)
        if len(queries) >= max_queries:
            break
    return queries


def _poi_refine_candidate(candidate: Candidate, *, cache_country_bias: bool = True) -> float:
    """Use forward geocoding on extracted queries to snap to precise coordinates.

    Returns a confidence adjustment. Modifies candidate in-place if a strong match is found.
    """
    queries = _extract_poi_queries(candidate)
    if not queries:
        return 0.0

    # Build search constraints
    cc = (candidate.country_code or "").lower() or None
    countrycodes = cc if cache_country_bias and cc and len(cc) == 2 else None
    bias = None
    if candidate.latitude is not None and candidate.longitude is not None:
        bias = (candidate.latitude, candidate.longitude)

    best = None
    best_score = -1e9
    for q in queries:
        results = forward_geocode(
            q,
            countrycodes=countrycodes,
            bias=bias,
            viewbox_km=100.0 if bias else None,
            limit=5,
        )
        if not results:
            continue
        for r in results:
            # Score candidate-r pair by multiple criteria
            score = 0.0
            # Country/admin consistency
            if candidate.country_name and r.country:
                if _normalize(candidate.country_name) == _normalize(r.country):
                    score += 2.0
                else:
                    score -= 3.0
            if candidate.admin1 and r.state:
                if _normalize(candidate.admin1) == _normalize(r.state):
                    score += 1.0
                else:
                    score -= 1.0
            # Distance from prior lat/lon if present
            if bias:
                d = haversine_distance(bias[0], bias[1], r.lat, r.lon)
                if d <= 10:
                    score += 3.0
                elif d <= 30:
                    score += 1.5
                elif d <= 80:
                    score += 0.5
                else:
                    score -= 1.5
            # Prefer results with city info
            if r.city:
                score += 0.3
            # Slight preference for shorter display names (more specific)
            if r.display_name:
                score += max(0.0, 0.6 - min(0.6, len(r.display_name) / 200.0))

            if score > best_score:
                best_score = score
                best = r

    if not best or best_score < 1.0:
        return 0.0

    # Adopt precise coordinates and tighten radius
    candidate.latitude = best.lat
    candidate.longitude = best.lon
    if best.city:
        candidate.nearest_city = candidate.nearest_city or best.city
    if best.state:
        candidate.admin1 = candidate.admin1 or best.state
    if best.country:
        candidate.country_name = candidate.country_name or best.country
    # Tighten radius if we snapped to a POI
    old_r = candidate.confidence_radius_km or 100.0
    candidate.confidence_radius_km = min(old_r, 5.0)
    # Boost confidence for a strong POI snap
    return 0.08


def _consistency_boost_via_reverse_geocode(candidates: list[Candidate], do_reverse: bool) -> None:
    """Boost candidates consistent with majority reverse-geocoded region among top-3.

    Modifies candidates in-place by slightly increasing confidence for those
    matching the majority country/admin1.
    """
    if not do_reverse:
        return
    # Gather up to three reverse-geocoded places
    places = []
    for c in candidates[:3]:
        if c.latitude is not None and c.longitude is not None:
            place = reverse_geocode(c.latitude, c.longitude)
            if place:
                places.append(place)
    if not places:
        return
    # Majority tallies
    from collections import Counter
    countries = Counter([p.country for p in places if p.country])
    admins = Counter([p.state for p in places if p.state])
    majority_country = countries.most_common(1)[0][0] if countries else None
    majority_admin = admins.most_common(1)[0][0] if admins else None
    if not majority_country and not majority_admin:
        return
    for c in candidates:
        boost = 0.0
        if majority_country and c.country_name and c.country_name == majority_country:
            boost += 0.05
        if majority_admin and c.admin1 and c.admin1 == majority_admin:
            boost += 0.03
        if boost:
            c.confidence = min(1.0, (c.confidence or 0.0) + boost)

def rank_and_finalize(image_path: str, model_name: str, raw: ModelOutput, top_k: int, do_reverse: bool) -> FinalResult:
    # First, collect all candidates
    all_candidates: List[Candidate] = [raw.primary_guess] + list(raw.alternatives)

    # Step 1: base refinement + local adjustments
    for c in all_candidates:
        c.confidence = refine_confidence(c)
        # Apply contradiction penalty (e.g., driving side)
        pen = contradiction_penalty(c)
        if pen:
            c.confidence = max(0.0, (c.confidence or 0.0) - pen)
        # Speed units and radius adjustments
        c.confidence = min(1.0, max(0.0, (c.confidence or 0.0) + speed_units_adjustment(c) + radius_adjustment(c)))

    # Optional Step 2: reverse-geocode per candidate to check consistency and enrich fields
    if do_reverse:
        for c in all_candidates[: max(3, top_k)]:  # limit lookups for performance
            adj = _geocode_consistency_adjust(c)
            if adj:
                c.confidence = min(1.0, max(0.0, (c.confidence or 0.0) + adj))

    # Optional Step 3: cluster-based small boosts
    cluster_adj = _cluster_adjustments(all_candidates)
    for idx, adj in cluster_adj.items():
        c = all_candidates[idx]
        c.confidence = min(1.0, max(0.0, (c.confidence or 0.0) + adj))

    # Optional Step 3.5: POI-based snapping for top few candidates (uses network)
    if do_reverse:
        for c in all_candidates[: max(3, top_k)]:
            try:
                adj = _poi_refine_candidate(c)
                if adj:
                    c.confidence = min(1.0, max(0.0, (c.confidence or 0.0) + adj))
            except Exception:
                # Be conservative; ignore any failures
                pass

    # Sort after adjustments
    all_candidates.sort(key=lambda c: c.confidence if c.confidence is not None else 0.0, reverse=True)

    # Optional Step 4: encourage consistency among top candidates using reverse geocoding majority, then re-rank
    _consistency_boost_via_reverse_geocode(all_candidates, do_reverse)
    all_candidates.sort(key=lambda c: c.confidence if c.confidence is not None else 0.0, reverse=True)

    # Fix ranks
    for i, c in enumerate(all_candidates, start=1):
        c.rank = i

    if do_reverse and all_candidates and all_candidates[0].latitude is not None and all_candidates[0].longitude is not None:
        place = reverse_geocode(all_candidates[0].latitude, all_candidates[0].longitude)
        if place:
            # Fill missing admin/city using reverse-geocode and adjust confidence
            pg = all_candidates[0]
            orig_completeness = sum(1 for x in [pg.country_name, pg.admin1, pg.admin2, pg.nearest_city] if x)
            
            # Update missing fields
            pg.country_name = pg.country_name or place.country
            pg.admin1 = pg.admin1 or place.state
            pg.admin2 = pg.admin2 or place.county
            pg.nearest_city = pg.nearest_city or place.city
            
            # Calculate how many fields were filled by reverse geocoding
            new_completeness = sum(1 for x in [pg.country_name, pg.admin1, pg.admin2, pg.nearest_city] if x)
            completeness_improvement = (new_completeness - orig_completeness) / 4
            
            # Boost confidence slightly if reverse geocoding added significant data
            if completeness_improvement > 0:
                pg.confidence = min(1.0, pg.confidence + (completeness_improvement * 0.1))

    top = all_candidates[: top_k]
    return FinalResult(
        image_path=image_path,
        model=model_name,
        primary_guess=top[0],
        top_k=top,
    )

