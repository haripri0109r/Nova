"""
Browser backend – placeholder for web navigation intents.
"""
from __future__ import annotations
import logging
from typing import Any, Dict

log = logging.getLogger("nova.backends.browser")

def handle(payload: Dict) -> Any:
    """Open URL in default browser."""
    # TODO: implement via webbrowser or automation.chrome
    raise NotImplementedError