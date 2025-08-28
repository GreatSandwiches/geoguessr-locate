from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from dotenv import load_dotenv

from .model_client import analyze_image, DEFAULT_MODEL
from .analysis import rank_and_finalize
from .cache import Cache
from .types import FinalResult

app = typer.Typer(add_completion=False, help="Guess a rough location from a GeoGuessr screenshot")
console = Console()


def _print_human(result: FinalResult) -> None:
    table = Table(title=f"Primary guess — model: {result.model}")
    table.add_column("Rank", justify="right")
    table.add_column("Confidence")
    table.add_column("Country")
    table.add_column("Region")
    table.add_column("City")
    table.add_column("Lat,Lon")
    table.add_row(
        str(result.primary_guess.rank),
        f"{result.primary_guess.confidence:.2f}",
        result.primary_guess.country_name or "?",
        result.primary_guess.admin1 or "?",
        result.primary_guess.nearest_city or "?",
        (
            f"{result.primary_guess.latitude:.3f}, {result.primary_guess.longitude:.3f}"
            if result.primary_guess.latitude is not None and result.primary_guess.longitude is not None
            else "?"
        ),
    )
    console.print(table)

    alt = Table(title="Top candidates")
    alt.add_column("Rank", justify="right")
    alt.add_column("Conf")
    alt.add_column("Country")
    alt.add_column("Region")
    alt.add_column("City")
    for c in result.top_k:
        alt.add_row(
            str(c.rank),
            f"{c.confidence:.2f}",
            c.country_name or "?",
            c.admin1 or "?",
            c.nearest_city or "?",
        )
    console.print(alt)


def _print_human2(result: FinalResult) -> None:
    def _format_cues(cues) -> str:
        if not cues:
            return "—"
        parts = []
        if getattr(cues, "driving_side", None):
            parts.append(f"Driving: {cues.driving_side}")
        if getattr(cues, "languages_seen", None):
            try:
                parts.append("Languages: " + ", ".join(cues.languages_seen))
            except Exception:
                pass
        if getattr(cues, "signage_features", None):
            parts.append(f"Signage: {cues.signage_features}")
        if getattr(cues, "road_markings", None):
            parts.append(f"Road: {cues.road_markings}")
        if getattr(cues, "vegetation_climate", None):
            parts.append(f"Env: {cues.vegetation_climate}")
        if getattr(cues, "electrical_infrastructure", None):
            parts.append(f"Infra: {cues.electrical_infrastructure}")
        if getattr(cues, "other_cues", None):
            parts.append(f"Other: {cues.other_cues}")
        return "\n".join(p for p in parts if p) or "—"

    table = Table(title=f"Primary guess — model: {result.model}")
    table.add_column("Rank", justify="right")
    table.add_column("Confidence")
    table.add_column("Country")
    table.add_column("Region")
    table.add_column("City")
    table.add_column("Lat,Lon")
    table.add_row(
        str(result.primary_guess.rank),
        f"{result.primary_guess.confidence:.2f}",
        result.primary_guess.country_name or "?",
        result.primary_guess.admin1 or "?",
        result.primary_guess.nearest_city or "?",
        (
            f"{result.primary_guess.latitude:.3f}, {result.primary_guess.longitude:.3f}"
            if result.primary_guess.latitude is not None and result.primary_guess.longitude is not None
            else "?"
        ),
    )
    console.print(table)

    alt = Table(title="Top candidates")
    alt.add_column("Rank", justify="right")
    alt.add_column("Conf")
    alt.add_column("Country")
    alt.add_column("Region")
    alt.add_column("City")
    for c in result.top_k:
        alt.add_row(
            str(c.rank),
            f"{c.confidence:.2f}",
            c.country_name or "?",
            c.admin1 or "?",
            c.nearest_city or "?",
        )
    console.print(alt)

    console.print("[bold]Primary clues[/bold]")
    console.print(_format_cues(result.primary_guess.cues))
    if result.primary_guess.reasons:
        console.print("[bold]Reasoning[/bold]")
        console.print(result.primary_guess.reasons)

@app.command()
def main(
    image: Path = typer.Argument(..., exists=True, readable=True, help="Path to screenshot"),
    top_k: int = typer.Option(5, min=1, max=10, help="Number of candidates to return"),
    model: str = typer.Option(DEFAULT_MODEL, help="Gemini model name"),
    json_out: Optional[Path] = typer.Option(None, help="Write full JSON to this file"),
    no_reverse_geocode: bool = typer.Option(False, help="Disable reverse geocoding"),
    clear_cache: bool = typer.Option(False, help="Clear local cache before running"),
    json_only: bool = typer.Option(False, help="Print only JSON to stdout"),
):
    """Analyze IMAGE and print a rough location guess."""
    load_dotenv()  # allow .env

    cache = Cache()
    if clear_cache:
        cache.clear()

    raw = analyze_image(str(image), top_k=top_k, model_name=model, cache=cache)
    final = rank_and_finalize(str(image), model, raw, top_k=top_k, do_reverse=not no_reverse_geocode)

    if json_only or json_out:
        payload = json.loads(final.model_dump_json())
        if json_only:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        if json_out:
            json_out.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human2(final)


if __name__ == "__main__":
    app()

