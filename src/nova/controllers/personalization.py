"""
Personalization controller – wallpaper, theme, dark mode, taskbar, start menu.
"""

import logging
import sys
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.personalization")


class PersonalizationController(BaseController):
    domain = "personalization"
    description = "Wallpaper, theme, dark mode, taskbar, start menu."

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        try:
            if operation == "wallpaper":
                path = intent.get("path")
                if not path:
                    return {"status": "error", "detail": "Missing wallpaper path"}
                import ctypes
                ctypes.windll.user32.SystemParametersInfoW(20, 0, path, 3)
                return {"status": "ok", "detail": f"Wallpaper set to {path}"}

            if operation == "theme":
                theme = intent.get("theme")
                if not theme:
                    return {"status": "error", "detail": "Missing theme name"}
                # Use PowerShell to set theme
                import subprocess
                subprocess.run(["powershell", "-Command", f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name AppsUseLightTheme -Value {0 if theme == 'dark' else 1}"], check=True)
                return {"status": "ok", "detail": f"Theme set to {theme}"}

            if operation == "dark_mode":
                enable = intent.get("enable", True)
                import subprocess
                val = 0 if enable else 1
                subprocess.run(["powershell", "-Command", f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize' -Name AppsUseLightTheme -Value {val}"], check=True)
                return {"status": "ok", "detail": f"Dark mode {'enabled' if enable else 'disabled'}"}

            if operation == "taskbar":
                setting = intent.get("setting")
                # Example: set taskbar alignment
                import subprocess
                subprocess.run(["powershell", "-Command", f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\Explorer\\Advanced' -Name TaskbarAl -Value {setting}"], check=True)
                return {"status": "ok", "detail": f"Taskbar setting applied: {setting}"}

            if operation == "start_menu":
                # placeholder
                return {"status": "ok", "detail": "Start menu customization not yet implemented"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("PersonalizationController failed")
            return {"status": "error", "detail": "Personalization operation failed"}


registry.register(PersonalizationController())