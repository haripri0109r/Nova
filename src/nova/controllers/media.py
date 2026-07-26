"""
Media controller – Spotify, YouTube, generic media controls.
"""

import logging
import subprocess
import sys
import urllib.parse
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.media")


class MediaController(BaseController):
    domain = "media"
    description = "Media playback controls (Spotify, YouTube, generic media keys)."

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        try:
            if operation == "spotify":
                action = intent.get("action", "play")
                key_map = {"play": "PlayPause", "pause": "PlayPause", "next": "NextTrack", "previous": "PreviousTrack"}
                vk = key_map.get(action)
                if not vk:
                    return {"status": "error", "detail": f"Unknown Spotify action {action}"}
                if sys.platform == "win32":
                    ps = f"(New-Object -ComObject WScript.Shell).SendKeys('{vk}')"
                    subprocess.run(["powershell", "-Command", ps], check=True)
                else:
                    subprocess.run(["playerctl", "-p", "spotify", action], check=True)
                return {"status": "ok", "detail": f"Spotify {action}"}

            if operation == "youtube":
                query = intent.get("query")
                if not query:
                    return {"status": "error", "detail": "Missing YouTube query"}
                url = "https://www.youtube.com/results?search_query=" + urllib.parse.quote(query)
                if sys.platform == "win32":
                    subprocess.Popen(["start", "", url], shell=True)
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", url])
                else:
                    subprocess.Popen(["xdg-open", url])
                return {"status": "ok", "detail": f"Opened YouTube search for {query}"}

            if operation == "media_control":
                # generic media keys
                action = intent.get("action", "play")
                key_map = {"play": "PlayPause", "pause": "PlayPause", "next": "NextTrack", "previous": "PreviousTrack"}
                vk = key_map.get(action)
                if not vk:
                    return {"status": "error", "detail": f"Unknown media action {action}"}
                if sys.platform == "win32":
                    ps = f"(New-Object -ComObject WScript.Shell).SendKeys('{vk}')"
                    subprocess.run(["powershell", "-Command", ps], check=True)
                else:
                    subprocess.run(["playerctl", action], check=True)
                return {"status": "ok", "detail": f"Media {action}"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("MediaController failed")
            return {"status": "error", "detail": "Media operation failed"}


registry.register(MediaController())