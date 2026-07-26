"""
Edge skill – open URL in Microsoft Edge.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.browser.edge")


def _edge_executable() -> str | None:
    if sys.platform != "win32":
        return None
    import os
    import shutil

    # Edge stable
    candidates = [
        os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "Microsoft", "Edge", "Application", "msedge.exe"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge", "Application", "msedge.exe"),
    ]
    for p in candidates:
        if os.path.isfile(p):
            return p
    return shutil.which("msedge")


class EdgeSkill(BaseSkill):
    intent = "open_browser"
    description = "Open a URL in Microsoft Edge."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "open_browser" and intent_data.get("browser", "").lower() == "edge"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        url = intent_data.get("url", "https://www.bing.com")
        exe = _edge_executable()
        if not exe:
            logger.warning("Edge not found")
            return {"status": "error", "message": "Edge not installed"}
        try:
            subprocess.Popen([exe, "--new-window", url], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            logger.info("Opened %s in Edge", url)
            return {"status": "ok", "detail": f"Opened {url} in Edge"}
        except Exception:
            logger.exception("EdgeSkill failed")
            return {"status": "error", "message": "Failed to open Edge"}


registry.register(EdgeSkill())