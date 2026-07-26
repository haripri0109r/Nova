"""
Application closer skill – close an application by name using taskkill / pkill.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.applications.closer")


class AppCloserSkill(BaseSkill):
    intent = "close_application"
    description = "Close a running application by name."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "close_application"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        app_name = intent_data.get("application")
        if not app_name:
            logger.warning("AppCloserSkill called without application name")
            return {"status": "error", "message": "Missing application name"}

        try:
            if sys.platform == "win32":
                # Use taskkill /IM
                subprocess.run(["taskkill", "/IM", f"{app_name}.exe", "/F"], check=False)
            else:
                subprocess.run(["pkill", "-f", app_name], check=False)
            logger.info("Sent close signal for %s", app_name)
            return {"status": "ok", "detail": f"Close signal sent to {app_name}"}
        except Exception:
            logger.exception("AppCloserSkill failed")
            return {"status": "error", "message": "Failed to close application"}


registry.register(AppCloserSkill())