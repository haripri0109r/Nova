#!/usr/bin/env python3
"""
Entry point: wires audio_input + clap_detector + automation + tts.
Reproduces run_double_clap_actions() and main() from the original nova.py exactly.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import time

import sounddevice as sd

from .config import (
    SAMPLE_RATE,
    BLOCK_MS,
    CHANNELS,
    MIN_DOUBLE_GAP_S,
    MAX_DOUBLE_GAP_S,
    SPIKE_RATIO,
    COOLDOWN_S,
    SONG_URI,
    FOCUS_EXISTING_CURSOR_ON_DOUBLE_CLAP,
    OPEN_NEW_CURSOR_ON_DOUBLE_CLAP,
    CURSOR_OPEN_FULLSCREEN,
    OPEN_CLAUDE_CODE_IN_CHROME,
    OPEN_BINANCE_BTC_IN_CHROME,
    OPEN_CHROME_FULLSCREEN,
    CLAUDE_CHROME_MONITOR,
    BINANCE_CHROME_MONITOR,
    NOVA_WELCOME_ENABLED,
    NOVA_WELCOME_PHRASE,
    NOVA_AFTER_SONG_DELAY_S,
    elevenlabs_env_config,
)
from .audio_input import block_samples, rms_mono, _choose_input_device
from .clap_detector import ClapDetector
from .automation.spotify import play_song
from .automation.chrome import open_claude_in_chrome, open_binance_btc_in_chrome
from .automation.cursor_editor import open_cursor_window
from .tts import say_nova_welcome

log = logging.getLogger("clap_listen")


def run_double_clap_actions() -> None:
    """Run outside the mic loop so sleeps do not stall capture."""
    play_song(SONG_URI)
    open_claude_in_chrome()
    open_binance_btc_in_chrome()
    if NOVA_WELCOME_ENABLED and NOVA_WELCOME_PHRASE.strip():
        delay = max(0.0, NOVA_AFTER_SONG_DELAY_S)
        if delay:
            time.sleep(delay)
        threading.Thread(target=say_nova_welcome, daemon=True).start()
    open_cursor_window()


def main() -> int:
    blocksize = block_samples()

    log.info(
        "Listening (double clap: %.2f-%.2fs apart, rate=%d, block=%d ms, "
        "spike_ratio=%.1f, cooldown=%.2fs). Ctrl+C to stop.",
        MIN_DOUBLE_GAP_S,
        MAX_DOUBLE_GAP_S,
        SAMPLE_RATE,
        BLOCK_MS,
        SPIKE_RATIO,
        COOLDOWN_S,
    )
    if SONG_URI.strip():
        log.info("Double clap opens this track: %s", SONG_URI.strip())
    else:
        log.info("SONG_URI is empty — set it to play one song on each double clap.")
    if FOCUS_EXISTING_CURSOR_ON_DOUBLE_CLAP:
        log.info(
            "Double clap will foreground an existing Cursor window (Windows API); "
            "falls back to launching Cursor if none is running."
        )
    if OPEN_NEW_CURSOR_ON_DOUBLE_CLAP:
        log.info("Double clap will also open a new Cursor window (-n).")
    if CURSOR_OPEN_FULLSCREEN and sys.platform == "win32":
        log.info("Cursor will be sent F11 for fullscreen after focus/launch.")
    if OPEN_CLAUDE_CODE_IN_CHROME:
        cu = (os.environ.get("CLAUDE_CODE_URL") or "https://claude.ai/new").strip()
        log.info(
            "After Spotify, open Claude in Chrome%s on monitor %d: %s",
            " fullscreen" if OPEN_CHROME_FULLSCREEN else "",
            CLAUDE_CHROME_MONITOR,
            cu,
        )
    if OPEN_BINANCE_BTC_IN_CHROME:
        bu = (
            os.environ.get("BINANCE_BTC_URL")
            or "https://www.binance.com/en/trade/BTC_USDT"
        ).strip()
        log.info(
            "After Spotify, open Binance BTC in Chrome%s on monitor %d: %s",
            " fullscreen" if OPEN_CHROME_FULLSCREEN else "",
            BINANCE_CHROME_MONITOR,
            bu,
        )
    if NOVA_WELCOME_ENABLED:
        ev, em, ef, er = elevenlabs_env_config()
        log.info(
            "After song + %.2fs: %r (ElevenLabs voice=%s, model=%s, format=%s, pcm_rate=%d)",
            NOVA_AFTER_SONG_DELAY_S,
            NOVA_WELCOME_PHRASE.strip(),
            ev or "(unset)",
            em,
            ef,
            er,
        )

    input_idx = _choose_input_device(blocksize)

    detector = ClapDetector()
    welcome_sequence_done = False

    try:
        with sd.InputStream(
            device=input_idx,
            samplerate=SAMPLE_RATE,
            channels=CHANNELS,
            dtype="float32",
            blocksize=blocksize,
        ) as stream:
            while True:
                data, overflowed = stream.read(blocksize)
                if overflowed:
                    log.warning("Input overflow; try a larger BLOCK_MS")

                level = rms_mono(data)

                if detector.update(level):
                    if not welcome_sequence_done:
                        welcome_sequence_done = True
                        log.info(
                            "Double clap detected (gap=%.3fs, rms=%.5f, "
                            "noise_floor=%.5f, threshold=%.5f) — running welcome once",
                            detector.last_gap,
                            level,
                            detector.state.noise_floor,
                            detector.threshold,
                        )
                        threading.Thread(
                            target=run_double_clap_actions, daemon=True
                        ).start()

    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0
    except sd.PortAudioError as e:
        log.error("Audio error: %s", e)
        log.error("If PortAudio fails, install/repair drivers or try another SAMPLE_RATE.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
