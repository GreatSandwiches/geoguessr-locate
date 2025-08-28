import os
from pathlib import Path

from geoguessr_locate.cli import main

def test_imports():
    assert callable(main)


