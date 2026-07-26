"""
Spotify skill – play/pause/next/previous via Spotify URI or media keys.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.media.spotify")


class SpotifySkill(BaseSkill):
    intent = "media_control"
    description = "Control Spotify playback."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "media_control" and intent_data.get("app", "").lower() == "spotify"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action", "").lower()
        try:
            if sys.platform == "win32":
                # Use media keys via PowerShell (simulate key presses)
                key_map = {
                    "play": "PlayPause",
                    "pause": "PlayPause",
                    "next": "NextTrack",
                    "previous": "PreviousTrack",
                }
                vk = key_map.get(action)
                if not vk:
                    logger.warning("Unknown Spotify action %s", action)
                    return {"status": "error", "message": f"Unknown action {action}"}
                ps_cmd = f"(New-Object -ComObject WScript.Shell).SendKeys('{vk}')"
                subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            else:
                # Use playerctl on Linux
                cmd_map = {
                    "play": "play",
                    "pause": "pause",
                    "next": "next",
                    "previous": "previous",
                }
                if action not in cmd_map:
                    return {"status": "error", "message": f"Unknown action {action}"}
                subprocess.run(["playerctl", "-p", "spotify", cmd_map[action]], check=True)

            logger.info("Spotify %s executed", action)
            return {"status": "ok", "detail": f"Spotify {action}"}
        except Exception:
            logger.exception("SpotifySkill failed")
            return {"status": "error", "message": "Failed to control Spotify"}


registry.register(SpotifySkill())