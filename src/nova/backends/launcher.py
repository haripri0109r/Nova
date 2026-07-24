"""
Launcher backend – handle app.open intents using existing AppLauncher.
"""
from __future__ import annotations
import logging
from typing import Any, Dict

log = logging.getLogger("nova.backends.launcher")

def handle(payload: Dict) -> Any:
    """Launch an application."""
    # TODO: delegate to modules.launcher.app_launcher.get_app_launcher()
    raise NotImplementedError