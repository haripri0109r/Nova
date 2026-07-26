"""
Media controller – Spotify, YouTube, generic media controls.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.media")


class MediaController(BaseController):
    intent = "media"
    description = "Media playback (Spotify, YouTube, generic media keys)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        app = intent_data.get("application", "spotify").lower()

        try:
            if operation == "play" or operation == "pause":
                return self._media_key(app, "PlayPause")
            if operation == "next":
                return self._media_key(app, "NextTrack")
            if operation == "previous":
                return self._media_key(app, "PreviousTrack")
            if operation == "open":
                if app == "spotify":
                    subprocess.Popen(["spotify:"])
                    return {"status": "ok", "detail": "Spotify opened"}
                if app == "youtube":
                    import urllib.parse, subprocess
                    query = intent_data.get("query", "")
                    url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
                    subprocess.Popen(["start", "", url], shell=True)
                    return {"status": "ok", "detail": f"Opened YouTube search for {query}"}
                return {"status": "error", "detail": f"Unknown media app {app}"}
            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("MediaController failed")
            return {"status": "error", "detail": "Media operation failed"}

    def _media_key(self, app: str, key: str) -> Dict[str, Any]:
        try:
            if sys.platform == "win32":
                # Send key via PowerShell
                vk_map = {"PlayPause": "0xB3", "NextTrack": "0xB0", "PreviousTrack": "0xB1"}
                vk = vk_map.get(key)
                if not vk:
                    return {"status": "error", "detail": f"Unknown key {key}"}
                ps = f"(New-Object -ComObject WScript.Shell).SendKeys([char]0x{vk[2:]})"
                subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
            else:
                # Linux using playerctl
                cmd = {"PlayPause": "play-pause", "NextTrack": "next", "PreviousTrack": "previous"}[key]
                subprocess.run(["playerctl", "-p", app, cmd], check=True)
            return {"status": "ok", "detail": f"Sent {key} to {app}"}
        except Exception:
            logger.exception("Media key failed")
            return {"status": "error", "detail": f"Failed to send {key}"}