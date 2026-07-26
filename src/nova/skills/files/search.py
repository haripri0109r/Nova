"""
File search skill – find files by name using system search (Windows Search / locate).
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.files.search")


class FileSearchSkill(BaseSkill):
    intent = "find_file"
    description = "Search for files by name."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "find_file"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        pattern = intent_data.get("pattern")
        if not pattern:
            logger.warning("FileSearchSkill called without pattern")
            return {"status": "error", "message": "Missing search pattern"}

        try:
            results: List[str] = []
            if sys.platform == "win32":
                # Use dir /s /b for simple recursive search
                cmd = ["cmd", "/c", f"dir /s /b *{pattern}*"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                results = [line.strip() for line in result.stdout.splitlines() if line.strip()]
            else:
                # Use find
                cmd = ["find", "/", "-name", f"*{pattern}*"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                results = [line.strip() for line in result.stdout.splitlines() if line.strip()]

            # Limit results
            results = results[:20]
            logger.info("Found %d files for pattern %s", len(results), pattern)
            return {"status": "ok", "detail": results}
        except Exception:
            logger.exception("FileSearchSkill failed")
            return {"status": "error", "message": "File search failed"}


registry.register(FileSearchSkill())