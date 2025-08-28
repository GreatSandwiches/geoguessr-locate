from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


class Cues(BaseModel):
    driving_side: Optional[str] = Field(None, description="left or right")
    languages_seen: Optional[list[str]] = None
    signage_features: Optional[str] = None
    road_markings: Optional[str] = None
    vegetation_climate: Optional[str] = None
    electrical_infrastructure: Optional[str] = None
    other_cues: Optional[str] = None


class Candidate(BaseModel):
    rank: int
    confidence: float = Field(ge=0.0, le=1.0)
    country_code: Optional[str] = None  # ISO-3166-1 alpha-2
    country_name: Optional[str] = None
    admin1: Optional[str] = None  # state/province/region
    admin2: Optional[str] = None  # county/district
    nearest_city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    confidence_radius_km: Optional[float] = None
    reasons: Optional[str] = None
    cues: Optional[Cues] = None


class ModelOutput(BaseModel):
    primary_guess: Candidate
    alternatives: List[Candidate]


class FinalResult(BaseModel):
    image_path: str
    model: str
    primary_guess: Candidate
    top_k: List[Candidate]

