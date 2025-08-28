from __future__ import annotations

from typing import List

from .types import ModelOutput, Candidate, FinalResult
from .geocode import reverse_geocode


def rank_and_finalize(image_path: str, model_name: str, raw: ModelOutput, top_k: int, do_reverse: bool) -> FinalResult:
    # Ensure ranking by confidence; primary is already rank 1
    all_candidates: List[Candidate] = [raw.primary_guess] + list(raw.alternatives)
    all_candidates.sort(key=lambda c: c.confidence if c.confidence is not None else 0.0, reverse=True)

    # Fix ranks
    for i, c in enumerate(all_candidates, start=1):
        c.rank = i

    if do_reverse and all_candidates and all_candidates[0].latitude is not None and all_candidates[0].longitude is not None:
        place = reverse_geocode(all_candidates[0].latitude, all_candidates[0].longitude)
        if place:
            # Fill missing admin/city using reverse-geocode, without overwriting confident model outputs
            pg = all_candidates[0]
            pg.country_name = pg.country_name or place.country
            pg.admin1 = pg.admin1 or place.state
            pg.admin2 = pg.admin2 or place.county
            pg.nearest_city = pg.nearest_city or place.city

    top = all_candidates[: top_k]
    return FinalResult(
        image_path=image_path,
        model=model_name,
        primary_guess=top[0],
        top_k=top,
    )

