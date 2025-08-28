# WARP.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

This is a Python CLI/GUI application that analyzes GeoGuessr screenshots using Google Gemini Vision to predict geographic locations. The tool provides structured output with primary guesses and alternative candidates, including confidence scores, coordinates, and reverse-geocoded location names.

### Core Architecture

The application follows a modular pipeline architecture:

1. **Image Analysis Pipeline**: `model_client.py` handles Google Gemini Vision API calls with retry logic and caching
2. **Post-processing**: `analysis.py` ranks candidates and enriches with reverse-geocoded data via OpenStreetMap Nominatim
3. **Output Generation**: Structured Pydantic models in `types.py` ensure consistent JSON schema
4. **Dual Interface**: Both CLI (`cli.py`) and GUI (`gui.py`) frontends using the same core logic
5. **Caching Layer**: `cache.py` provides local file-based caching to reduce API costs during development

### Key Components

- **Prompt Engineering**: `prompts.py` contains carefully crafted prompts with versioning for consistent model behavior
- **Reverse Geocoding**: `geocode.py` integrates with Nominatim API for place name resolution
- **GUI Implementation**: Tkinter-based GUI with image preview, interactive maps (Folium), and clipboard integration
- **Utilities**: `utils.py` provides image processing and file hashing utilities

## Development Commands

### Setup
```powershell
# Install dependencies in development mode
pip install -e .

# Or using uv (recommended)
uv venv
.venv\Scripts\Activate.ps1
uv pip install -e .
```

### Running the Application
```powershell
# CLI usage
geoguessr-locate path/to/screenshot.jpg --top-k 5 --json-out result.json

# GUI mode
geoguessr-locate-gui

# View CLI help
geoguessr-locate --help
```

### Code Quality and Testing
```powershell
# Format code (configured for 100-character line length)
black .
ruff check .

# Run tests (minimal smoke test exists)
python -m pytest tests/ -v

# Clear application cache
geoguessr-locate --clear-cache path/to/image.jpg
```

### Configuration

#### Required Environment Variables
- `GOOGLE_API_KEY`: Google Generative AI API key (required)

#### Optional Environment Variables  
- `GEOGUESSR_LOCATE_MODEL`: Override default model (currently `gemini-2.5-flash-lite`)
- `GEOGUESSR_LOCATE_CACHE`: Custom cache directory path

Configuration via `.env` file is supported and recommended for local development.

## Project Structure

```
geoguessr_locate/
├── __init__.py
├── cli.py          # Typer-based CLI interface
├── gui.py          # Tkinter GUI with map visualization
├── model_client.py # Gemini API client with caching/retry
├── analysis.py     # Post-processing and ranking logic
├── types.py        # Pydantic models for structured data
├── prompts.py      # Versioned prompt templates
├── geocode.py      # Nominatim reverse geocoding
├── cache.py        # File-based caching system
└── utils.py        # Image processing utilities
```

## Development Notes

### API Integration Patterns
- All Gemini API calls use exponential backoff retry logic via `tenacity`
- Caching keys include model name, prompt version, and image hash for proper invalidation
- Response parsing includes robust error handling for malformed JSON

### GUI Architecture
- Uses threading for non-blocking API calls with Tkinter event loop integration
- Automatic map generation and browser launch for result visualization
- Clipboard integration for both image input and coordinate output

### Data Flow
1. Image → SHA256 hash for cache key generation
2. Cache lookup → Skip API call if hit
3. Gemini Vision API → Structured JSON response via Pydantic validation
4. Ranking/post-processing → Merge reverse-geocoded data
5. Output → CLI tables (Rich) or GUI display with interactive maps

### Error Handling
- Network failures trigger automatic retries with backoff
- Invalid JSON responses are caught and re-attempted
- Missing API keys provide clear error messages
- File I/O errors are handled gracefully in both interfaces

### Performance Considerations
- Local caching significantly reduces API costs during iteration
- Image thumbnailing in GUI prevents memory issues with large screenshots
- Lazy loading of maps and expensive operations
