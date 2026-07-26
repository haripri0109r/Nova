"""
Chrome skill – open URL in Chrome.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.browser.chrome")


def _chrome_executable() -> str | None:
    if sys.platform != "win32":
        return None
    import os
    import shutil

    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        if not base:
            continue
        path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.isfile(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chrome")


class ChromeSkill(BaseSkill):
    intent = "open_browser"
    description = "Open a URL in Google Chrome."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "open_browser" and intent_data.get("browser", "").lower() == "chrome"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        url = intent_data.get("url", "https://www.google.com")
        exe = _chrome_executable()
        if not exe:
            logger.warning("Chrome not found")
            return {"status": "error", "message": "Chrome not installed"}
        try:
            subprocess.Popen([exe, "--new-window", url], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            logger.info("Opened %s in Chrome", url)
            return {"status": "ok", "detail": f"Opened {url} in Chrome"}
        except Exception:
            logger.exception("ChromeSkill failed")
            return {"status": "error", "message": "Failed to open Chrome"}


registry.register(ChromeSkill())