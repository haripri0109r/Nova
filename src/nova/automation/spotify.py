#!/usr/bin/env python3
"""
Spotify/URL playback automation.
"""

from __future__ import annotations

import logging
import os
import sys
import webbrowser

log = logging.getLogger("nova")


def play_song(uri: str) -> None:
    u = uri.strip()
    if not u:
        return
    try:
        if sys.platform == "win32":
            os.startfile(u)
        else:
            webbrowser.open(u)
    except OSError as e:
        log.warning("Could not open SONG_URI: %s", e)