import os
from pathlib import Path

import subprocess

def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    subprocess.run(cmd, check=True)

if __name__ == "__main__":
    # Developer helper to install locally with pip
    if not Path(".venv").exists():
        print("[hint] Create and activate a venv before running this script")
    run(["python", "-m", "pip", "install", "-e", "."])
