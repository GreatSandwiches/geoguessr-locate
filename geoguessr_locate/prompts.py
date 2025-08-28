PROMPT_VERSION = "v1"

SYSTEM_PROMPT = (
    "You are a professional GeoGuessr geolocation analyst. "
    "Given a single street-level photo, infer where it is with high accuracy. "
    "Explain your reasoning succinctly and extract cues such as languages, driving side, road markings, signage, vegetation, and electrical infrastructure. "
    "Return JSON ONLY that conforms to the provided schema. Do not include markdown or commentary outside JSON."
)

USER_PROMPT_TEMPLATE = """
Task: Analyze the attached image and provide a primary guess and top-<<TOP_K_MINUS_1>> alternative candidates.

Definitions:
- Rough area = country, primary admin area (state/province/region), nearest major city.
- Also include an estimated lat/lon and confidence radius (km). Confidence is 0..1.
- Use ISO-3166-1 alpha-2 for country_code when possible.

JSON schema (return exactly this structure, fields may be null when unknown):
{
  "primary_guess": {
    "rank": 1,
    "confidence": float,
    "country_code": string|null,
    "country_name": string|null,
    "admin1": string|null,
    "admin2": string|null,
    "nearest_city": string|null,
    "latitude": float|null,
    "longitude": float|null,
    "confidence_radius_km": float|null,
    "reasons": string|null,
    "cues": {
      "driving_side": "left"|"right"|null,
      "languages_seen": [string, ...]|null,
      "signage_features": string|null,
      "road_markings": string|null,
      "vegetation_climate": string|null,
      "electrical_infrastructure": string|null,
      "other_cues": string|null
    }
  },
  "alternatives": [
    {
      "rank": 2,
      "confidence": float,
      "country_code": string|null,
      "country_name": string|null,
      "admin1": string|null,
      "admin2": string|null,
      "nearest_city": string|null,
      "latitude": float|null,
      "longitude": float|null,
      "confidence_radius_km": float|null,
      "reasons": string|null,
      "cues": {
        "driving_side": "left"|"right"|null,
        "languages_seen": [string, ...]|null,
        "signage_features": string|null,
        "road_markings": string|null,
        "vegetation_climate": string|null,
        "electrical_infrastructure": string|null,
        "other_cues": string|null
      }
    }
  ]
}

Instructions:
- Be decisive but honest about uncertainty.
- Prefer country and region names in English when available.
- If specific coordinates are unclear, still provide a plausible lat/lon and a larger radius.
- Focus on street furniture, bollards, pole styles, guardrails, road center/edge lines, sign fonts/colors, language on signs, landscape and architecture.
- Return strictly valid JSON. No extra keys.
"""

