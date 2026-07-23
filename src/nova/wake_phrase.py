#!/usr/bin/env python3
"""
Wake‑phrase detection using Google Web Speech API via SpeechRecognition.

Provides:
* WakePhraseListener – captures full utterances from the microphone,
  sends them to Google's free recognize_google() endpoint, and returns
  the transcribed text (or None on failure).
* matches_wake_phrase – word‑boundary aware check for "hello/hey nova"
  (and known mis‑recognitions like "norma", "robot", "robert").
"""

from __future__ import annotations

import logging
import re
import speech_recognition as sr

log = logging.getLogger("nova")


class WakePhraseListener:
    """
    Listens for a single complete utterance using the default microphone,
    performs ambient‑noise calibration once at start‑up, then repeatedly
    returns recognised text (or None).
    """

    def __init__(self) -> None:
        self._recognizer = sr.Recognizer()
        self._mic = sr.Microphone()
        # Calibrate once for ambient noise
        with self._mic as source:
            log.info("Calibrating for ambient noise (1 s)…")
            self._recognizer.adjust_for_ambient_noise(source, duration=1.0)
        log.info("Wake‑phrase listener ready")

    # ------------------------------------------------------------------
    def listen_for_utterance(self) -> str | None:
        """
        Block until a full utterance is captured (speech followed by a pause)
        or the optional phrase_time_limit expires. Returns the recognised
        text, or None on failure.
        """
        with self._mic as source:
            try:
                audio = self._recognizer.listen(
                    source,
                    timeout=None,          # wait indefinitely for speech to start
                    phrase_time_limit=5.0, # max length of a single utterance
                )
            except sr.WaitTimeoutError:
                # No speech started within timeout (not used because timeout=None)
                return None

        try:
            text = self._recognizer.recognize_google(audio)
            return text
        except sr.UnknownValueError:
            # unintelligible – common during silence / background noise
            log.debug("Google STT could not understand audio")
            return None
        except sr.RequestError as exc:
            # network / API problem – warn but keep running
            log.warning("Google Web Speech API request failed: %s", exc)
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