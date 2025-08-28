from importlib.metadata import version as _v

__all__ = ["__version__"]

try:
    __version__ = _v("geoguessr-locate")
except Exception:  # pragma: no cover
    __version__ = "0.1.0"

