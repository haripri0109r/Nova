#!/usr/bin/env python3
"""
Command pattern registry and matching.

Each command is associated with a list of trigger patterns.
A pattern is a list of words that must appear consecutively (word-boundary)
in the recognised text (case-insensitive).
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

# -------------------------------------------------------------------------
# Command → list of patterns (each pattern is a list of words)
# -------------------------------------------------------------------------
COMMAND_PATTERNS: Dict[str, List[List[str]]] = {
    "open_chrome": [
        ["open", "chrome"],
        ["launch", "chrome"],
        ["start", "chrome"],
    ],
    "open_vscode": [
        ["open", "vs", "code"],
        ["open", "vscode"],
        ["open", "code"],
        ["launch", "vs", "code"],
        ["launch", "vscode"],
        ["launch", "code"],
    ],
    "shutdown": [
        ["shutdown"],
        ["shut", "down"],
        ["turn", "off", "computer"],
        ["turn", "off", "pc"],
        ["turn", "off", "the", "pc"],
    ],
    "restart": [
        ["restart"],
        ["reboot"],
        ["restart", "computer"],
        ["reboot", "computer"],
    ],
    "sleep": [
        ["sleep"],
        ["go", "to", "sleep"],
        ["put", "to", "sleep"],
        ["standby"],
    ],
    "mute_volume": [
        ["mute"],
        ["mute", "volume"],
        ["silence"],
    ],
    "set_volume": [
        ["set", "volume"],
        ["volume", "to"],
    ],
    "increase_brightness": [
        ["increase", "brightness"],
        ["brightness", "up"],
        ["brighten"],
    ],
    "decrease_brightness": [
        ["decrease", "brightness"],
        ["brightness", "down"],
        ["dim"],
    ],
}

# -------------------------------------------------------------------------
# Target words used for wake‑phrase detection (shared with wake_phrase.py)
# -------------------------------------------------------------------------
_TARGET_WORDS = {"nova", "norma", "robot", "robert", "nov"}

_GENERIC_OPEN_VERBS = {"open", "launch"}


def _words(text: str) -> List[str]:
    """Split text into lowercase alphanumeric words."""
    return re.split(r"[^a-z0-9']+", text.lower())


def extract_remainder(text: str) -> str:
    """
    Given a full recognised utterance that is known to contain a wake‑phrase,
    return the text that follows the wake‑phrase words.

    * If the wake‑phrase was the two‑word form "hello/hey <target>" the
      remainder is everything after that target word.
    * If the wake‑phrase was the short‑utterance fallback (1‑2 words that are
      just a target word) the remainder is empty.
    * If no wake‑phrase pattern is found (should not happen when called from
      main.py) an empty string is returned.
    """
    if not text:
        return ""
    # split on non‑alphanumeric, keep only real words
    words = [w for w in re.split(r"[^a-z0-9']+", text.lower()) if w]

    # 1️⃣ two‑word wake phrase:  hello/hey  <target>
    for i in range(len(words) - 1):
        if words[i] in ("hello", "hey") and words[i + 1] in _TARGET_WORDS:
            # everything after the target word is the command
            return " ".join(words[i + 2 :])

    # 2️⃣ short‑utterance fallback (1‑2 words, one of them a target)
    if len(words) <= 2 and any(w in _TARGET_WORDS for w in words):
        return ""

    return ""


def _match_exact(text: str) -> Optional[str]:
    """Run the original high‑priority pattern table."""
    if not text:
        return None
    words = [w for w in _words(text) if w]
    for cmd, patterns in COMMAND_PATTERNS.items():
        for pat in patterns:
            plen = len(pat)
            for i in range(len(words) - plen + 1):
                if words[i:i + plen] == pat:
                    return cmd
    return None


# -------------------------------------------------------------------------
# Generic “open / launch <app>” extractor – runs *after* the exact patterns
# -------------------------------------------------------------------------


def extract_generic_app(text: str) -> Optional[str]:
    """
    If *text* looks like  "open <app>"  or  "launch <app>"
    (case‑insensitive, whole‑word “open”/“launch” followed by ≥1 word)
    return the extracted app name, otherwise ``None``.
    """
    if not text:
        return None
    words = _words(text)
    for i, w in enumerate(words):
        if w in _GENERIC_OPEN_VERBS and i + 1 < len(words):
            # everything after the verb is the app name
            return " ".join(words[i + 1 :])
    return None


def match_command(text: str) -> Optional[str]:
    """
    Return the command name whose pattern matches *text*, or None.
    Patterns are checked in the order of COMMAND_PATTERNS dict.
    """
    # First try the exact, high‑priority patterns (unchanged)
    exact = _match_exact(text)
    if exact:
        return exact

    # Low‑priority generic “open/launch <app>”
    generic = extract_generic_app(text)
    if generic:
        return "open_generic"

    return None