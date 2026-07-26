"""
Explorer skill – open a folder in File Explorer.
"""

import logging
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.files.explorer")


class ExplorerSkill(BaseSkill):
    intent = "open_folder"
    description = "Open a folder in the system file explorer."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "open_folder"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        path_str = intent_data.get("path")
        if not path_str:
            logger.warning("ExplorerSkill called without path")
            return {"status": "error", "message": "Missing folder path"}

        path = Path(path_str).expanduser().resolve()
        if not path.is_dir():
            logger.warning("Path not a directory: %s", path)
            return {"status": "error", "message": f"Not a directory: {path}"}

        try:
            if sys.platform == "win32":
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
            logger.info("Opened folder %s", path)
            return {"status": "ok", "detail": f"Opened folder {path}"}
        except Exception:
            logger.exception("ExplorerSkill failed")
            return {"status": "error", "message": "Failed to open folder"}


registry.register(ExplorerSkill())