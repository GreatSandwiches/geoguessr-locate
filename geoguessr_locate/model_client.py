from __future__ import annotations

import json
import os
from typing import List

import google.generativeai as genai
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pydantic import ValidationError

from .utils import load_image_bytes, sha256_file
from .ocr import extract_ocr_text
from .cache import Cache
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, PROMPT_VERSION
from .types import ModelOutput, Candidate


DEFAULT_MODEL = os.environ.get("GEOGUESSR_LOCATE_MODEL", "gemini-2.5-flash-lite")


def _configure_client() -> None:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set. Set it in env or .env")
    genai.configure(api_key=api_key)


class JsonParseError(RuntimeError):
    pass


@retry(
    wait=wait_exponential(multiplier=1, min=2, max=20),
    stop=stop_after_attempt(3),
    retry=retry_if_exception_type((JsonParseError, RuntimeError)),
)
def analyze_image(
    image_path: str,
    top_k: int = 5,
    model_name: str = DEFAULT_MODEL,
    cache: Cache | None = None,
) -> ModelOutput:
    """Call Gemini Vision on an image and return structured candidates."""
    _configure_client()

    cache = cache or Cache()
    img_hash = sha256_file(image_path)[:16]
    cache_key = f"gemini_{model_name}_{PROMPT_VERSION}_{top_k}_{img_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            return ModelOutput(**cached)
        except ValidationError:
            pass

    image_bytes = load_image_bytes(image_path)
    # Optional OCR to aid the model with sign text; safe no-op if unavailable
    ocr_text = extract_ocr_text(image_path) or ""

    system = SYSTEM_PROMPT
    user = USER_PROMPT_TEMPLATE.replace("<<TOP_K_MINUS_1>>", str(max(1, top_k - 1)))
    user = user.replace("<<OCR_TEXT>>", ocr_text)

    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=system,
        generation_config={
            "temperature": 0.2,            # lower for determinism
            "top_p": 0.8,                  # slightly narrower nucleus sampling
            "top_k": 50,                   # consider more candidates
            "response_mime_type": "application/json",
        },
    )

    content = [
        {"mime_type": "image/jpeg", "data": image_bytes},
        user,
    ]

    try:
        resp = model.generate_content(content, request_options={"timeout": 120})
    except Exception as e:
        raise RuntimeError(f"Gemini call failed: {e}")

    # Robust JSON parsing with simple recovery from markdown fences or extra text
    try:
        text = resp.text
        data = _parse_model_json(text)
        output = ModelOutput(**data)
    except Exception as e:
        raise JsonParseError(f"Failed to parse model JSON: {e}")

    cache.set(cache_key, json.loads(output.model_dump_json()))
    return output


def _parse_model_json(text: str) -> dict:
    """Parse model output into JSON dict with light recovery.

    - Tries direct json.loads
    - Strips markdown code fences if present
    - Extracts first {...} block as fallback
    """
    # Direct parse
    try:
        return json.loads(text)
    except Exception:
        pass
    # Strip markdown code fences
    if "```" in text:
        stripped = text
        # remove ```json or ``` fences
        stripped = stripped.replace("```json", "```")
        parts = stripped.split("```")
        # pick the largest fenced block as likely JSON
        if len(parts) >= 3:
            candidates = [p for i, p in enumerate(parts) if i % 2 == 1]
            if candidates:
                largest = max(candidates, key=lambda s: len(s))
                try:
                    return json.loads(largest)
                except Exception:
                    text = largest
    # Find first/last braces fallback
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        snippet = text[start : end + 1]
        return json.loads(snippet)
    # Give up
    return json.loads(text)

