from __future__ import annotations

import json
import os
from typing import List

import google.generativeai as genai
try:  # optional dependency
    from openai import OpenAI  # type: ignore
except Exception:  # pragma: no cover - openai may not be installed in minimal env
    OpenAI = None  # type: ignore
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pydantic import ValidationError

from .utils import load_image_bytes, sha256_file
from .ocr import extract_ocr_text
from .cache import Cache
from .prompts import SYSTEM_PROMPT, USER_PROMPT_TEMPLATE, USER_PROMPT_TEMPLATE_OPENAI, PROMPT_VERSION
from .types import ModelOutput, Candidate


GEMINI_DEFAULT_MODEL = os.environ.get("GEOGUESSR_LOCATE_GEMINI_MODEL", "gemini-2.5-flash-lite")
OPENAI_DEFAULT_MODEL = os.environ.get("GEOGUESSR_LOCATE_OPENAI_MODEL", "gpt-5-nano")
DEFAULT_PROVIDER = os.environ.get("GEOGUESSR_LOCATE_PROVIDER", "gemini")  # gemini or openai
# Backwards compatible single default
DEFAULT_MODEL = os.environ.get("GEOGUESSR_LOCATE_MODEL", GEMINI_DEFAULT_MODEL)


def _configure_gemini() -> None:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY not set. Set it in env or .env")
    genai.configure(api_key=api_key)


def _configure_openai():  # -> OpenAI
    if OpenAI is None:
        raise RuntimeError("openai package not installed. Install with pip install openai")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set. Set it in env or .env")
    return OpenAI(api_key=api_key)


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
    use_ocr: bool = True,
    provider: str = DEFAULT_PROVIDER,
) -> ModelOutput:
    """Call selected provider (Gemini or OpenAI) on an image and return structured candidates.

    provider: 'gemini' (default) or 'openai'
    For OpenAI, expects a vision-capable model (e.g., 'gpt-4o-mini') supporting
    image + system/user messages and JSON mode or reliable JSON output.
    """
    provider = provider.lower()
    cache = cache or Cache()
    img_hash = sha256_file(image_path)[:16]
    cache_key = f"{provider}_{model_name}_{PROMPT_VERSION}_{top_k}_{img_hash}"
    cached = cache.get(cache_key)
    if cached is not None:
        try:
            return ModelOutput(**cached)
        except ValidationError:
            pass

    # Adjust model default dynamically if caller didn't override and provider switched
    if provider == "openai" and (model_name == DEFAULT_MODEL or model_name.startswith("gemini")):
        model_name = OPENAI_DEFAULT_MODEL
    elif provider == "gemini" and model_name == DEFAULT_MODEL and model_name.startswith("gpt"):
        model_name = GEMINI_DEFAULT_MODEL

    image_bytes = load_image_bytes(image_path)
    ocr_text = extract_ocr_text(image_path) or "" if use_ocr else ""
    system = SYSTEM_PROMPT
    base_template = USER_PROMPT_TEMPLATE_OPENAI if provider == "openai" else USER_PROMPT_TEMPLATE
    user = base_template.replace("<<TOP_K_MINUS_1>>", str(max(1, top_k - 1)))
    user = user.replace("<<OCR_TEXT>>", ocr_text or "(none)")

    if provider == "gemini":
        _configure_gemini()
        model = genai.GenerativeModel(
            model_name=model_name,
            system_instruction=system,
            generation_config={
                "temperature": 0.15,
                "top_p": 0.7,
                "top_k": 40,
                "response_mime_type": "application/json",
            },
        )
        content = [
            {"mime_type": "image/jpeg", "data": image_bytes},
            user,
        ]
        try:
            resp = model.generate_content(content, request_options={"timeout": 120})
            text = resp.text
        except Exception as e:
            raise RuntimeError(f"Gemini call failed: {e}")
    elif provider == "openai":
        client = _configure_openai()
        # OpenAI images: send base64 data url or bytes via content array
        import base64
        b64 = base64.b64encode(image_bytes).decode("utf-8")
        messages = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": user},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                ],
            },
        ]
        # Primary attempt: ask for JSON response
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                response_format={"type": "json_object"},
            )
        except Exception as first_err:
            # Fallback: try without forcing response_format (some preview models may not support it)
            try:
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=messages,
                )
            except Exception:
                raise RuntimeError(f"OpenAI call failed: {first_err}")
        text = completion.choices[0].message.content or ""
    else:
        raise RuntimeError(f"Unknown provider '{provider}'. Use 'gemini' or 'openai'.")

    try:
        data = _parse_model_json(text)
        output = ModelOutput(**data)
        _sanitize_precision(output)
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


def _sanitize_precision(output: ModelOutput) -> None:
    """Reduce false precision by clearing lat/lon when radius is broad or unsupported.

    - If radius > 150km, nullify coordinates (too vague for pinpoint).
    - If coords present but radius missing, set a conservative minimum (25km)
      unless reasons mention an explicit road/route pattern.
    """
    import re

    route_pattern = re.compile(r"\b(I-?\d+|US ?\d+|A\d+|E\d+|M\d+|BR-?\d+|SP-?\d+|N\d+|D\d+|R\d+)\b", re.I)

    def adjust(c: Candidate) -> None:
        if c.latitude is None or c.longitude is None:
            return
        r = c.confidence_radius_km
        if r is not None and r > 150:
            c.latitude = None
            c.longitude = None
            return
        if r is None:
            if not route_pattern.search(c.reasons or ""):
                c.confidence_radius_km = 25.0

    adjust(output.primary_guess)
    for alt in output.alternatives:
        adjust(alt)


