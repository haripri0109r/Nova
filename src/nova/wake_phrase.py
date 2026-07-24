#!/usr/bin/env python3
"""
Wake‑phrase detection using Google Web Speech API via SpeechRecognition.

Provides:
* WakePhraseListener – captures a single complete utterance from the default
  microphone, sends it to Google’s free Web Speech endpoint and returns the
  transcribed text (or None on failure/timeout).
* matches_wake_phrase – word‑boundary aware check for "hello/hey nova"
  (and known mis‑recognitions "norma", "robot", "robert").
"""

from __future__ import annotations

import logging
import re
import threading
from pathlib import Path

import speech_recognition as sr

from .config import settings
from .audio_input import _choose_input_device, block_samples

log = logging.getLogger("nova")


class WakePhraseListener:
    """
    Listens for a single utterance using Google's free Web Speech API.

    Parameters
    ----------
    model_path : str | Path | None
        Ignored – kept for API compatibility with the old Vosk version.
    sample_rate : int | None
        Input audio sample‑rate (must match the microphone stream, default
        ``settings.sample_rate`` = 44100 Hz).
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        sample_rate: int | None = None,
    ) -> None:
        # The model_path argument is kept for compatibility but unused.
        self._sample_rate = sample_rate or settings.sample_rate

        # ---- SpeechRecognition setup ------------------------------------
        self._recognizer = sr.Recognizer()
        # Allow longer pauses between words so phrases like "to forty" aren't split
        self._recognizer.pause_threshold = 1.2
        # Probe the microphone once so we can reuse the same device index.
        self._blocksize = block_samples()
        self._device_idx = _choose_input_device(self._blocksize)
        self._mic = sr.Microphone(
            device_index=self._device_idx,
            sample_rate=self._sample_rate,
            chunk_size=self._blocksize,
        )
        # One‑time ambient calibration — avoids 1‑2 s dead air on every listen() call
        with self._mic as source:
            self._recognizer.adjust_for_ambient_noise(source, duration=1.0)
        self._recognizer.dynamic_energy_threshold = False
        self._recognizer.energy_threshold = 300

    # ------------------------------------------------------------------
    # Public blocking API used by main.py
    # ------------------------------------------------------------------
    def listen_for_utterance(
        self,
        stop_event: threading.Event | None = None,
        timeout: float | None = None,
        phrase_time_limit: float | None = None,
    ) -> str | None:
        """
        Block until a single utterance is recognised (or the call times out).

        Parameters
        ----------
        stop_event : threading.Event | None
            If the event is **already set** when the call starts we return
            ``None`` immediately.  (The underlying ``recognizer.listen`` call
            cannot be interrupted once it has started, so the event is only
            checked *before* the blocking call.)
        timeout : float | None
            Seconds to wait for speech to start (``recognizer.listen`` timeout).
            ``None`` means wait indefinitely.
        phrase_time_limit : float | None
            Max utterance length after speech is detected.  Defaults to
            *timeout* if given, otherwise 15 s.  Callers can pass a shorter
            limit (e.g. 3 s) for short one‑word responses.

        Returns
        -------
        str | None
            The transcribed text, or ``None`` on timeout / recognition failure
            / network error.
        """
        if stop_event is not None and stop_event.is_set():
            log.debug("listen_for_utterance aborted – stop_event already set")
            return None

        if phrase_time_limit is not None:
            phrase_limit = phrase_time_limit
        elif timeout is not None:
            phrase_limit = timeout
        else:
            phrase_limit = 15.0

        log.debug("listen_for_utterance: waiting for speech (timeout=%s, phrase_limit=%s)", timeout, phrase_limit)
        try:
            with self._mic as source:
                # ``listen`` blocks until speech is detected and then until a
                # pause (or ``phrase_time_limit``) ends the utterance.
                audio = self._recognizer.listen(
                    source,
                    timeout=timeout,
                    phrase_time_limit=phrase_limit,
                )
        except (sr.WaitTimeoutError, OSError):
            log.debug("listen_for_utterance: WaitTimeoutError/OSError (no speech or mic busy)")
            return None

        log.debug("listen_for_utterance: got audio, recognizing...")
        try:
            text = self._recognizer.recognize_google(audio)
            log.debug("recognize_google returned: %r", text)
            return text
        except sr.UnknownValueError:
            log.debug("recognize_google: UnknownValueError (unintelligible)")
            return None
        except sr.RequestError as exc:
            log.warning("Google Web Speech API request failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Legacy push‑API (kept for any external caller)
    # ------------------------------------------------------------------
    def listen(self, audio_block: np.ndarray) -> str | None:
        """
        Feed a single audio block and return whatever text the recogniser has
        (final **or** partial).  Exists for backward compatibility;
        ``main.py`` does **not** call this method.
        """
        # The push API is not meaningful with the cloud recogniser – keep it
        # as a no‑op placeholder to avoid import‑time breakage.
        return None

    # ------------------------------------------------------------------
    @staticmethod
    def matches_wake_phrase(text: str) -> bool:
        """
        Return True if *text* contains a wake phrase.

        Primary rule (word‑boundary aware):
        * "hello" or "hey" immediately followed by one of the target words:
          "nova", "norma", "robot", "robert".

        Fallback (conservative):
        * If the whole utterance is 1‑2 words and any word is a target word,
          treat it as a deliberate short command.
        """
        if not text:
            return False
        lowered = text.lower()
        words = re.split(r"[^a-z0-9']+", lowered)
        target_words = {"nova", "norma", "robot", "robert"}

        # Primary two‑word check
        for i in range(len(words) - 1):
            if words[i] in ("hello", "hey") and words[i + 1] in target_words:
                return True

        # Fallback for very short utterances consisting only of a target word
        if len(words) <= 2 and any(w in target_words for w in words):
            return True

        return False