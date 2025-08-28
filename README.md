# geoguessr-locate

A Python CLI that analyzes a GeoGuessr screenshot with Google Gemini Vision and predicts a rough area (country, region/state, nearest major city), returning a primary guess plus top-k alternatives. It can optionally reverse-geocode coordinates via OpenStreetMap Nominatim.

Status: v0.1.0

Features
- Google Gemini Vision (gemini-2.5-flash-lite by default) for multimodal reasoning
- Heuristics: language on signs, road features, driving side, signage types, vegetation, architecture
- Outputs human-readable summary and JSON (top-k candidates with confidence)
- Optional reverse-geocoding via Nominatim to name regions and cities
- Local caching to reduce costs during iteration
- Refined confidence scoring that blends model confidence, visual cue completeness, and location specificity; reverse geocoding can boost confidence when it fills missing details
- GUI screen capture and hotkeys: Capture button plus F9 / Ctrl+Shift+S global hotkeys to capture even when minimized
- Prompt v2 with more detailed guidance for higher-quality geolocation analysis
- Configurable model via GEOGUESSR_LOCATE_MODEL environment variable

Quick start
1) Prereqs: Python 3.11+
2) Create a virtualenv and install:
   - With uv (recommended):
     uv venv
     source .venv/bin/activate
     uv pip install -e .
   - Or pip:
     python3 -m venv .venv
     source .venv/bin/activate
     pip install -e .
3) Configure credentials:
   - Copy .env.example to .env and set GOOGLE_API_KEY (or export it in your shell)
4) Run (CLI):
   geoguessr-locate path/to/screenshot.jpg --top-k 5 --json-out result.json
5) Run (GUI):
   geoguessr-locate-gui
   - Use Browse or Paste to load an image, or use Capture to grab the current screen
   - Global hotkeys: Press F9 or Ctrl+Shift+S to capture while the app is in the background

Environment
- GOOGLE_API_KEY: your Google Generative AI key
- GEOGUESSR_LOCATE_CACHE: optional path to cache directory
- GEOGUESSR_LOCATE_MODEL: optional model override (default: gemini-2.5-flash-lite)

Nominatim notes
- This tool uses the public Nominatim API with a custom User-Agent and light caching.
- Be respectful: rate limited to at most 1 req/sec. For heavy usage, set up your own instance.

License
MIT

