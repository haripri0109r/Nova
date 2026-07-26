"""
YouTube skill – open a YouTube video or search.
"""

import logging
import urllib.parse
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.media.youtube")


class YouTubeSkill(BaseSkill):
    intent = "play_media"
    description = "Play a video on YouTube."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "play_media" and intent_data.get("app", "").lower() == "youtube"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        query = intent_data.get("query")
        if not query:
            logger.warning("YouTubeSkill called without query")
            return {"status": "error", "message": "Missing video query"}

        # If it's a full URL, open directly; otherwise search
        if query.startswith("http"):
            url = query
        else:
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"

        try:
            if sys.platform == "win32":
                subprocess.Popen(["start", "", url], shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
            logger.info("Opened YouTube %s", url)
            return {"status": "ok", "detail": f"Opened YouTube {url}"}
        except Exception:
            logger.exception("YouTubeSkill failed")
            return {"status": "error", "message": "Failed to open YouTube"}


registry.register(YouTubeSkill())