#!/usr/bin/env python3
"""
Entry point: wires wake_phrase + automation + tts.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from .config import settings, elevenlabs_env_config
from .wake_phrase import WakePhraseListener
from .automation.spotify import play_song
from .automation.chrome import open_claude_in_chrome, open_binance_btc_in_chrome
from .automation.cursor_editor import open_cursor_window
from .tts import say_nova_welcome

log = logging.getLogger("nova")


def run_wake_actions() -> None:
    """Run the same five actions as the old wake‑phrase flow."""
    play_song(settings.song_uri)
    open_claude_in_chrome()
    open_binance_btc_in_chrome()
    if settings.nova_welcome_enabled and settings.nova_welcome_phrase.strip():
        delay = max(0.0, settings.nova_after_song_delay_s)
        if delay:
            time.sleep(delay)
        threading.Thread(target=say_nova_welcome, daemon=True).start()
    open_cursor_window()


def main() -> int:
    logging.basicConfig(
        level=getattr(logging, settings.nova_log_level),
        format="%(levelname)s:%(name)s:%(message)s",
    )

    log.info(
        "Listening for wake phrase 'hello nova' (Google Web Speech API). Ctrl+C to stop."
    )
    if settings.song_uri.strip():
        log.info("Wake phrase opens this track: %s", settings.song_uri.strip())
    else:
        log.info("SONG_URI is empty — set it to play a song on each wake phrase.")
    if settings.focus_existing_cursor_on_wake:
        log.info(
            "Wake phrase will foreground an existing Cursor window (Windows API); "
            "falls back to launching Cursor if none is running."
        )
    if settings.open_new_cursor_on_wake:
        log.info("Wake phrase will also open a new Cursor window (-n).")
    if settings.cursor_open_fullscreen and sys.platform == "win32":
        log.info("Cursor will be sent F11 for fullscreen after focus/launch.")
    if settings.open_claude_code_in_chrome:
        cu = settings.claude_code_url
        log.info(
            "After Spotify, open Claude in Chrome%s on monitor %d: %s",
            " fullscreen" if settings.open_chrome_fullscreen else "",
            settings.claude_chrome_monitor,
            cu,
        )
    if settings.open_binance_btc_in_chrome:
        bu = settings.binance_btc_url
        log.info(
            "After Spotify, open Binance BTC in Chrome%s on monitor %d: %s",
            " fullscreen" if settings.open_chrome_fullscreen else "",
            settings.binance_chrome_monitor,
            bu,
        )
    if settings.nova_welcome_enabled:
        ev, em, ef, er = elevenlabs_env_config()
        log.info(
            "After song + %.2fs: %r (ElevenLabs voice=%s, model=%s, format=%s, pcm_rate=%d)",
            settings.nova_after_song_delay_s,
            settings.nova_welcome_phrase.strip(),
            ev or "(unset)",
            em,
            ef,
            er,
        )

    wake_listener = WakePhraseListener()
    welcome_sequence_done = False

    try:
        while True:
            text = wake_listener.listen_for_utterance()
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
    except Exception as e:
        log.error("Unexpected error: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())