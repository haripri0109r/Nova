#!/usr/bin/env python3
"""
Entry point: wires audio_input + wake_phrase + automation + tts.
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
    SONG_URI,
    FOCUS_EXISTING_CURSOR_ON_WAKE,
    OPEN_NEW_CURSOR_ON_WAKE,
    CURSOR_OPEN_FULLSCREEN,
    OPEN_CLAUDE_CODE_IN_CHROME,
    OPEN_BINANCE_BTC_IN_CHROME,
    OPEN_CHROME_FULLSCREEN,
    CLAUDE_CHROME_MONITOR,
    BINANCE_CHROME_MONITOR,
    NOVA_WELCOME_ENABLED,
    NOVA_WELCOME_PHRASE,
    NOVA_AFTER_SONG_DELAY_S,
    NOVA_LOG_LEVEL,
    elevenlabs_env_config,
)
from .audio_input import block_samples, _choose_input_device
from .wake_phrase import WakePhraseListener
from .automation.spotify import play_song
from .automation.chrome import open_claude_in_chrome, open_binance_btc_in_chrome
from .automation.cursor_editor import open_cursor_window
from .tts import say_nova_welcome

log = logging.getLogger("nova")


def run_wake_actions() -> None:
    """Run the same five actions as the old wake‑phrase flow."""
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
    logging.basicConfig(level=NOVA_LOG_LEVEL, format="%(levelname)s:%(name)s:%(message)s")
    blocksize = block_samples()

    log.info(
        "Listening for wake phrase 'hello nova' (rate=%d, block=%d ms). Ctrl+C to stop.",
        SAMPLE_RATE,
        BLOCK_MS,
    )
    if SONG_URI.strip():
        log.info("Wake phrase opens this track: %s", SONG_URI.strip())
    else:
        log.info("SONG_URI is empty — set it to play a song on each wake phrase.")
    if FOCUS_EXISTING_CURSOR_ON_WAKE:
        log.info(
            "Wake phrase will foreground an existing Cursor window (Windows API); "
            "falls back to launching Cursor if none is running."
        )
    if OPEN_NEW_CURSOR_ON_WAKE:
        log.info("Wake phrase will also open a new Cursor window (-n).")
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

    wake_listener = WakePhraseListener()
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

                # data shape (blocksize, channels) -> mono float32
                if data.ndim > 1:
                    audio_block = data[:, 0]
                else:
                    audio_block = data

                text = wake_listener.listen(audio_block)
                if text is not None:
                    log.debug("Heard: %r", text)
                if text and WakePhraseListener.matches_wake_phrase(text):
                    if not welcome_sequence_done:
                        welcome_sequence_done = True
                        log.info(
                            "Wake phrase detected: %r — running welcome once", text
                        )
                        threading.Thread(
                            target=run_wake_actions, daemon=True
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