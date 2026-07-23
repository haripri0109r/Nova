#!/usr/bin/env python3
"""
Wake‑phrase detection using Vosk (offline STT).

Provides:
* WakePhraseListener – feeds audio blocks, returns recognised text when
  Vosk produces a final or partial result.
* matches_wake_phrase – word‑boundary aware check for "hello nova" or
  "hey nova".
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

try:
    from vosk import KaldiRecognizer, Model
except Exception as exc:  # pragma: no cover – handled at runtime
    Model = None  # type: ignore
    KaldiRecognizer = None  # type: ignore
    _VOSK_IMPORT_ERROR = exc
else:
    _VOSK_IMPORT_ERROR = None

from .config import SAMPLE_RATE, VOSK_MODEL_PATH

log = logging.getLogger("nova")


class WakePhraseListener:
    """
    Streaming wake‑phrase listener backed by Vosk.

    Parameters
    ----------
    model_path : str | Path
        Path to the unpacked Vosk model directory (must contain `am/`,
        `conf/`, `graph/` etc.).  Defaults to ``config.VOSK_MODEL_PATH``.
    sample_rate : int
        Input audio sample rate (must match the mic stream, default
        ``config.SAMPLE_RATE`` = 44100 Hz).  Vosk models expect 16000 Hz,
        so we resample internally.
    """

    _TARGET_RATE = 16000  # Vosk model sample rate

    def __init__(
        self,
        model_path: str | Path | None = None,
        sample_rate: int = SAMPLE_RATE,
    ) -> None:
        if Model is None:  # vosk not importable
            raise RuntimeError(
                "vosk is not installed. Install it with `pip install vosk`."
            ) from _VOSK_IMPORT_ERROR

        self._sample_rate = sample_rate
        self._up = self._TARGET_RATE
        self._down = sample_rate

        model_path = Path(model_path or VOSK_MODEL_PATH).expanduser().resolve()
        if not model_path.exists():
            raise FileNotFoundError(
                f"Vosk model not found at {model_path}. "
                "Run `python scripts/download_vosk_model.py` to fetch it."
            )

        log.info("Loading Vosk model from %s", model_path)
        self._model = Model(str(model_path))
        self._rec = KaldiRecognizer(self._model, self._TARGET_RATE)
        self._rec.SetWords(True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def listen(self, audio_block: np.ndarray) -> str | None:
        """
        Feed one audio block (float32 mono, shape (N,)) from the microphone.

        Returns the recognised text (final or partial) if Vosk produced
        something, otherwise ``None``.
        """
        if audio_block.ndim != 1:
            audio_block = np.mean(audio_block, axis=1)

        # 1️⃣  Resample to 16 kHz (float32 → float32)
        block_16k = resample_poly(audio_block.astype(np.float32), self._up, self._down)

        # 2️⃣  Convert to 16‑bit PCM bytes for Vosk
        pcm16 = (block_16k * 32767.0).clip(-32768, 32767).astype(np.int16).tobytes()

        # 3️⃣  Feed Vosk
        if self._rec.AcceptWaveform(pcm16):
            result = json.loads(self._rec.Result())
            return result.get("text", "") or None

        # Also surface partial results for faster wake‑word reaction
        partial = json.loads(self._rec.PartialResult())
        txt = partial.get("partial", "")
        return txt if txt else None

    # ------------------------------------------------------------------
    @staticmethod
    def matches_wake_phrase(text: str) -> bool:
        """
        Return True if *text* contains a wake phrase.

        Primary rule (word‑boundary aware):
        * "hello" or "hey" immediately followed by one of the target words:
          "nova", "norma", "robot", "robert".

        Fallback rule (conservative):
        * If the final recognised text consists of 1‑2 words and the sole
          word (or last word) is one of the target words, treat it as a
          deliberate short command.  This avoids false triggers from longer
          sentences that merely contain the word.
        """
        if not text:
            return False
        lowered = text.lower()
        import re

        words = re.split(r"[^a-z0-9']+", lowered)
        # target words that can follow "hello"/"hey"
        target_words = {"nova", "norma", "robot", "robert"}

        # Primary two‑word check
        for i in range(len(words) - 1):
            if words[i] in ("hello", "hey") and words[i + 1] in target_words:
                return True

        # Fallback: short final result consisting only of a target word
        if len(words) <= 2:
            # check if any word in the short utterance is a target word
            if any(w in target_words for w in words):
                return True

        return False