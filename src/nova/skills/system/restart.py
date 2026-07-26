"""
Restart skill – uses Windows shutdown.exe /r.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.restart")


class RestartSkill(BaseSkill):
    intent = "restart"
    description = "Restart the computer."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "restart"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        if sys.platform != "win32":
            logger.warning("Restart only implemented on Windows")
            return {"status": "error", "message": "Unsupported platform"}
        try:
            subprocess.run(
                [r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"],
                check=True,
            )
            logger.info("Restart command issued")
            return {"status": "ok", "detail": "Restarting"}
        except Exception:
            logger.exception("RestartSkill failed")
            return {"status": "error", "message": "Restart failed"}


registry.register(RestartSkill())