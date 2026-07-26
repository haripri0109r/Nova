"""
Browser controller – open URLs in Chrome, Edge, Firefox.
"""

import logging
import subprocess
import sys
import shutil
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.browser")


class BrowserController(BaseController):
    domain = "browser"
    description = "Open URLs in Chrome, Edge, or Firefox."

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def _chrome_path(self) -> str | None:
        if sys.platform != "win32":
            return None
        import os
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

    def _edge_path(self) -> str | None:
        if sys.platform != "win32":
            return None
        import os
        candidates = [
            os.path.join(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                         "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"),
                         "Microsoft", "Edge", "Application", "msedge.exe"),
            os.path.join(os.environ.get("LOCALAPPDATA", ""),
                         "Microsoft", "Edge", "Application", "msedge.exe"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                return p
        return shutil.which("msedge")

    def _firefox_path(self) -> str | None:
        if sys.platform != "win32":
            return shutil.which("firefox")
        import os
        for base in (
            os.environ.get("ProgramFiles", r"C:\Program Files"),
            os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
            os.environ.get("LOCALAPPDATA", ""),
        ):
            if not base:
                continue
            p = os.path.join(base, "Mozilla Firefox", "firefox.exe")
            if os.path.isfile(p):
                return p
        return shutil.which("firefox")

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        url = intent.get("url")
        app = intent.get("application", "chrome").lower()
        if operation != "open":
            return {"status": "error", "detail": f"Unknown operation {operation}"}
        if not url:
            return {"status": "error", "detail": "Missing URL"}

        try:
            if app == "chrome":
                exe = self._chrome_path()
            elif app == "edge":
                exe = self._edge_path()
            elif app == "firefox":
                exe = self._firefox_path()
            else:
                return {"status": "error", "detail": f"Unsupported browser {app}"}
            if not exe:
                return {"status": "error", "detail": f"{app.capitalize()} not installed"}
            subprocess.Popen([exe, "--new-window", url],
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            return {"status": "ok", "detail": f"Opened {url} in {app.capitalize()}"}
        except Exception:
            logger.exception("BrowserController failed")
            return {"status": "error", "detail": "Failed to open browser"}


registry.register(BrowserController())