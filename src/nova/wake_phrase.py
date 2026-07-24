#!/usr/bin/env python3
"""
Wake‑phrase detection using Silero VAD + Faster‑Whisper (local, offline).

Provides:
* WakePhraseListener – captures a single utterance from the default microphone,
  stops when silence is detected, transcribes with Faster‑Whisper and returns
  the text (or None on failure/timeout).
* matches_wake_phrase – word‑boundary aware check for "hello/hey nova"
  (and known mis‑recognitions "norma", "robot", "robert").
"""

from __future__ import annotations

import logging
import re
import threading
import wave
from io import BytesIO
from pathlib import Path

import numpy as np
import sounddevice as sd
import torch
from faster_whisper import WhisperModel

from .config import settings
from .audio_input import _choose_input_device, block_samples

log = logging.getLogger("nova")

# ----------------------------------------------------------------------
# Silero VAD + Faster‑Whisper singleton loaders
# ----------------------------------------------------------------------
_VAD_MODEL = None
_WHISPER_MODEL = None


def _get_vad():
    """Load Silero VAD model once (torch.hub)."""
    global _VAD_MODEL
    if _VAD_MODEL is None:
        log.info("Loading Silero VAD model (torch.hub)…")
        _VAD_MODEL, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
            trust_repo=True,
        )
        _VAD_MODEL.eval()
        log.info("Silero VAD loaded.")
    return _VAD_MODEL


def _get_whisper():
    """Load Faster‑Whisper model once."""
    global _WHISPER_MODEL
    if _WHISPER_MODEL is None:
        model_name = settings.whisper_model
        log.info("Loading Faster‑Whisper model '%s'…", model_name)
        _WHISPER_MODEL = WhisperModel(model_name, device="auto", compute_type="int8")
        log.info("Faster‑Whisper loaded.")
    return _WHISPER_MODEL


# ----------------------------------------------------------------------
# WakePhraseListener
# ----------------------------------------------------------------------
class WakePhraseListener:
    """
    Listens for a single utterance using Silero VAD, stops on silence,
    transcribes locally with Faster‑Whisper, and returns the text.
    """

    def __init__(
        self,
        model_path: str | Path | None = None,
        sample_rate: int | None = None,
    ) -> None:
        # model_path kept for API compatibility (unused)
        self._sample_rate = sample_rate or settings.sample_rate

        # ---- device selection (reuse existing helper) -----------------
        self._blocksize = block_samples()
        self._device_idx = _choose_input_device(self._blocksize)

        # Pre‑load models (lazy, but cheap)
        _get_vad()
        _get_whisper()

    # ------------------------------------------------------------------
    # Public blocking API used by main.py
    # ------------------------------------------------------------------
    def listen_for_utterance(
        self,
        stop_event: threading.Event | None = None,
        timeout: float | None = None,
        phrase_time_limit: float | None = None,   # kept for signature compatibility
    ) -> str | None:
        """
        Block until an utterance is captured and transcribed.

        Parameters
        ----------
        stop_event : threading.Event | None
            If already set, abort immediately.
        timeout : float | None
            Seconds to wait for speech to start. ``None`` = wait forever.
        phrase_time_limit : float | None
            *Ignored* – VAD decides when the utterance ends.
        """
        if stop_event is not None and stop_event.is_set():
            log.debug("listen_for_utterance aborted – stop_event already set")
            return None

        log.debug("listen_for_utterance: waiting for speech (timeout=%s)", timeout)

        audio_bytes = self._record_until_silence(timeout)
        if not audio_bytes:
            return None

        # Transcribe with Faster‑Whisper
        try:
            text = self._transcribe(audio_bytes)
            log.debug("Faster‑Whisper returned: %r", text)
            return text.strip() if text else None
        except Exception as exc:                     # pragma: no cover
            log.warning("Transcription failed: %s", exc)
            return None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _record_until_silence(self, timeout: float | None) -> bytes | None:
        """Capture audio from the microphone until VAD reports silence."""
        vad_model = _get_vad()

        # Load all VAD / audio parameters from config
        vad_sr = settings.vad_sample_rate
        vad_frame = settings.vad_frame_size
        silence_ms = settings.vad_silence_ms
        max_utterance_s = settings.vad_max_utterance_s
        vad_thresh = settings.vad_threshold

        silence_frames_needed = int(silence_ms / (vad_frame / vad_sr * 1000))
        max_frames = int(max_utterance_s * vad_sr / vad_frame)

        speech_started = False
        silence_counter = 0
        recorded_frames = []

        try:
            with sd.InputStream(
                device=self._device_idx,
                samplerate=vad_sr,
                channels=1,
                dtype="int16",
                blocksize=vad_frame,
            ) as stream:
                start_time = None
                while True:
                    if timeout is not None and start_time is not None:
                        if (sd.default.timer() - start_time) > timeout:
                            log.debug("Timeout waiting for speech start")
                            return None

                    frame, _ = stream.read(vad_frame)   # shape (512,1)
                    frame = frame[:, 0]                 # mono 1‑D

                    # Convert to float32 tensor for VAD
                    tensor = torch.from_numpy(frame.astype(np.float32) / 32768.0).unsqueeze(0)
                    prob = vad_model(tensor, vad_sr).item()

                    if prob > vad_thresh:          # speech
                        if not speech_started:
                            speech_started = True
                            start_time = sd.default.timer()
                            log.debug("VAD: speech start (p=%.2f)", prob)
                        silence_counter = 0
                    else:                           # silence / noise
                        if speech_started:
                            silence_counter += 1
                            if silence_counter >= silence_frames_needed:
                                log.debug("VAD: silence detected, stopping")
                                break
                        # else still waiting for first speech

                    if speech_started:
                        recorded_frames.append(frame)

                    if len(recorded_frames) >= max_frames:
                        log.debug("Max utterance length reached")
                        break
        except Exception as exc:          # pragma: no cover
            log.error("Audio capture error: %s", exc)
            return None

        if not recorded_frames:
            return None

        # Concatenate frames and write an in‑memory WAV (16‑bit PCM)
        audio_data = np.concatenate(recorded_frames)
        wav_buffer = BytesIO()
        with wave.open(wav_buffer, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)          # 16‑bit
            wf.setframerate(vad_sr)
            wf.writeframes(audio_data.tobytes())
        wav_buffer.seek(0)
        return wav_buffer.read()

    def _transcribe(self, audio_bytes: bytes) -> str:
        """Run Faster‑Whisper on the given WAV bytes and return text."""
        model = _get_whisper()
        audio_stream = BytesIO(audio_bytes)
        segments, _ = model.transcribe(audio_stream, language="en", vad_filter=False)
        return " ".join(seg.text for seg in segments)

    # ------------------------------------------------------------------
    # Legacy push‑API (kept for any external caller)
    # ------------------------------------------------------------------
    def listen(self, audio_block: np.ndarray) -> str | None:
        """Not used by the new pipeline – kept for backward compatibility."""
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