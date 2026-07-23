#!/usr/bin/env python3
"""
Download and extract the Vosk small English model (vosk-model-small-en-us-0.15)
into the local `models/` directory.

Usage:
    python scripts/download_vosk_model.py
"""

import os
import sys
import urllib.request
import zipfile
from pathlib import Path

MODEL_NAME = "vosk-model-small-en-us-0.15"
MODEL_URL = f"https://alphacephei.com/vosk/models/{MODEL_NAME}.zip"
MODELS_DIR = Path(__file__).resolve().parent.parent / "models"
MODEL_DIR = MODELS_DIR / MODEL_NAME
ZIP_PATH = MODELS_DIR / f"{MODEL_NAME}.zip"


def download_model() -> None:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)

    if MODEL_DIR.exists():
        print(f"Model already present at {MODEL_DIR}")
        return

    print(f"Downloading {MODEL_NAME} (~40 MB) from {MODEL_URL} ...")
    try:
        urllib.request.urlretrieve(MODEL_URL, ZIP_PATH)
    except Exception as exc:
        print(f"Failed to download model: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Extracting...")
    try:
        with zipfile.ZipFile(ZIP_PATH, "r") as zf:
            zf.extractall(MODELS_DIR)
    except Exception as exc:
        print(f"Failed to extract model: {exc}", file=sys.stderr)
        sys.exit(1)
    finally:
        # clean up zip
        if ZIP_PATH.exists():
            ZIP_PATH.unlink()

    print(f"Model ready at {MODEL_DIR}")


if __name__ == "__main__":
    download_model()