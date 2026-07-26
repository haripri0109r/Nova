"""
Shutdown skill – uses Windows shutdown.exe.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.shutdown")


class ShutdownSkill(BaseSkill):
    intent = "shutdown"
    description = "Shut down the computer."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "shutdown"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        if sys.platform != "win32":
            logger.warning("Shutdown only implemented on Windows")
            return {"status": "error", "message": "Unsupported platform"}
        try:
            subprocess.run(
                [r"C:\Windows\System32\shutdown.exe", "/s", "/t", "0"],
                check=True,
            )
            logger.info("Shutdown command issued")
            return {"status": "ok", "detail": "Shutting down"}
        except Exception:
            logger.exception("ShutdownSkill failed")
            return {"status": "error", "message": "Shutdown failed"}


registry.register(ShutdownSkill())