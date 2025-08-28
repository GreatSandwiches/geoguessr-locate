from __future__ import annotations

from typing import List, Optional, Tuple
from math import radians, cos, sin, asin, sqrt

from .types import ModelOutput, Candidate, FinalResult, Cues
from .geocode import reverse_geocode


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

def rank_and_finalize(image_path: str, model_name: str, raw: ModelOutput, top_k: int, do_reverse: bool) -> FinalResult:
    # First, refine confidence scores for all candidates
    all_candidates: List[Candidate] = [raw.primary_guess] + list(raw.alternatives)
    
    for c in all_candidates:
        c.confidence = refine_confidence(c)
    
    # Sort by refined confidence scores
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

