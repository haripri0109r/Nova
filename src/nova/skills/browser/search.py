"""
Search skill – perform a web search using default browser.
"""

import logging
import urllib.parse
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.browser.search")


class SearchSkill(BaseSkill):
    intent = "web_search"
    description = "Perform a web search."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "web_search"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        query = intent_data.get("query")
        if not query:
            logger.warning("SearchSkill called without query")
            return {"status": "error", "message": "Missing search query"}

        # Use default browser via start (Windows) or xdg-open (Linux)
        url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
        try:
            if sys.platform == "win32":
                subprocess.Popen(["start", "", url], shell=True)
            elif sys.platform == "darwin":
                subprocess.Popen(["open", url])
            else:
                subprocess.Popen(["xdg-open", url])
            logger.info("Performed web search for %s", query)
            return {"status": "ok", "detail": f"Searching for {query}"}
        except Exception:
            logger.exception("SearchSkill failed")
            return {"status": "error", "message": "Failed to open browser for search"}


registry.register(SearchSkill())