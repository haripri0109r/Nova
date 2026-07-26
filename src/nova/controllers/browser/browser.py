"""
Browser controller – open URL in Chrome, Edge, Firefox.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.browser")


class BrowserController(BaseController):
    intent = "browser"
    description = "Open URLs in Chrome, Edge, or Firefox."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        url = intent_data.get("url")
        application = intent_data.get("application", "chrome")

        if operation != "open":
            return {"status": "error", "detail": f"Unknown operation {operation}"}
        if not url:
            return {"status": "error", "detail": "Missing URL"}

        def _chrome_path() -> str | None:
            if sys.platform != "win32":
                return None
            import os, shutil
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

        def _edge_path() -> str | None:
            if sys.platform != "win32":
                return None
            import os, shutil
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

        def _firefox_path() -> str | None:
            if sys.platform != "win32":
                return shutil.which("firefox")
            import os, shutil
            for base in (
                os.environ.get("ProgramFiles", r"C:\Program Files"),
                os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                os.environ.get("LOCALAPPDATA", ""),
            ):
                if not base:
                    continue
                path = os.path.join(base, "Mozilla Firefox", "firefox.exe")
                if os.path.isfile(path):
                    return path
            return shutil.which("firefox")

        try:
            app = application.lower()
            if app == "chrome":
                exe = _chrome_path()
            elif app == "edge":
                exe = _edge_path()
            elif app == "firefox":
                exe = _firefox_path()
            else:
                return {"status": "error", "detail": f"Unsupported browser {application}"}

            if not exe:
                return {"status": "error", "detail": f"{application} not installed"}

            subprocess.Popen([exe, "--new-window", url],
                             creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            return {"status": "ok", "detail": f"Opened {url} in {application.capitalize()}"}
        except Exception:
            logger.exception("BrowserController failed")
            return {"status": "error", "detail": "Failed to open browser"}