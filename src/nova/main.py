#!/usr/bin/env python3
"""
Entry point: wires wake_phrase + automation + tts + command routing.
"""

from __future__ import annotations

import logging
import string
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError

from .config import settings, elevenlabs_env_config
from .wake_phrase import WakePhraseListener
from .automation.spotify import play_song
from .automation.chrome import open_claude_in_chrome, open_binance_btc_in_chrome
from .automation.cursor_editor import open_cursor_window
from .tts import say_nova_welcome
from .system_actions import COMMAND_HANDLERS, DESTRUCTIVE_COMMANDS
from .commands import match_command, extract_remainder, extract_generic_app

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


def _listen_with_timeout(
    listener: WakePhraseListener,
    timeout: float,
    phrase_time_limit: float | None = None,
) -> str | None:
    """
    Call listener.listen_for_utterance(...) in a thread and enforce a timeout.
    Returns the recognised text or None on timeout / error.

    *timeout* controls how long to wait for speech to start.
    *phrase_time_limit* controls the max utterance length (defaults to *timeout*).
    The outer ``future.result()`` deadline is set to
    ``timeout + phrase_time_limit + 5`` to absorb Google API latency without
    discarding correctly‑captured audio.
    """
    ptl = phrase_time_limit if phrase_time_limit is not None else timeout
    future_timeout = timeout + ptl + 5.0

    stop_event = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(
            listener.listen_for_utterance,
            stop_event=stop_event,
            timeout=timeout,
            phrase_time_limit=ptl,
        )
        try:
            result = future.result(timeout=future_timeout)
            log.debug("[CONFIRM] listen_for_utterance returned: %r", result)
            return result
        except FuturesTimeoutError:
            log.warning("[CONFIRM] Timeout waiting for confirmation")
            stop_event.set()
            return None
        except Exception as exc:
            log.warning("listen_for_utterance failed during confirmation: %s", exc)
            stop_event.set()
            return None


def _confirm_action(listener: WakePhraseListener, prompt: str, timeout: float = 12.0) -> bool:
    """
    Speak (log) a confirmation prompt and wait for a short affirmative response.
    Returns True if user says an affirmative word within timeout, else False.
    """
    log.info(prompt)
    log.debug("[CONFIRM] Waiting for confirmation (timeout=%.1fs)...", timeout)
    resp = _listen_with_timeout(listener, timeout=timeout, phrase_time_limit=3.0)
    if not resp:
        log.debug("[CONFIRM] No response received (timeout or error)")
        return False
    log.debug("[CONFIRM] Raw recognized text: %r", resp)
    lowered = resp.lower()
    affirmative = {"yes", "yeah", "yep", "ye", "yea", "confirm", "ok", "okay", "sure", "proceed"}
    words = [w.strip(string.punctuation) for w in lowered.split()]
    if any(word in affirmative for word in words):
        log.info("[CONFIRM] Confirmation accepted (heard %r)", resp)
        return True
    log.debug("[CONFIRM] No affirmative word found in: %r", words)
    return False


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
            # --- Phase 1: wait for wake phrase (blocking, no timeout) ---
            text = wake_listener.listen_for_utterance()
            if text is not None:
                log.debug("Heard: %r", text)
            if text and WakePhraseListener.matches_wake_phrase(text):
                if not welcome_sequence_done:
                    welcome_sequence_done = True
                    log.info(
                        "Wake phrase detected: %r — listening for command", text
                    )

                # --- Phase 2a: try to extract a command from the SAME utterance ---
                remainder = extract_remainder(text)
                if remainder:
                    cmd_name = match_command(remainder)
                    command_text = remainder
                else:
                    cmd_name = None
                    command_text = None

                if cmd_name:
                    log.info("Command from same utterance: %r", remainder)
                else:
                    cmd_text = _listen_with_timeout(wake_listener, timeout=12.0, phrase_time_limit=12.0)
                    if cmd_text is not None:
                        log.debug("Command heard (second round): %r", cmd_text)
                    cmd_name = match_command(cmd_text) if cmd_text else None
                    command_text = cmd_text

                if not cmd_name:
                    # No recognisable command → just log and go back to listening
                    log.info("No command recognised; ignoring.")
                    continue

                handler = COMMAND_HANDLERS.get(cmd_name)
                if not handler:
                    log.warning("No handler for command %s", cmd_name)
                    continue

                if cmd_name in DESTRUCTIVE_COMMANDS:
                    if _confirm_action(
                        wake_listener,
                        f"Destructive command '{cmd_name}' requested. Say yes to confirm.",
                        timeout=12.0,
                    ):
                        log.info("Confirmation received — executing %s", cmd_name)
                        handler(command_text)
                    else:
                        log.info("Cancelled.")
                else:
                    log.info("Executing command: %s", cmd_name)
                    handler(command_text)

    except KeyboardInterrupt:
        log.info("Stopped.")
        return 0
    except Exception as e:
        log.error("Unexpected error: %s", e)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())