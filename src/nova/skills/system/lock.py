"""
Lock skill – locks the workstation using Windows API.
"""

import logging
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.lock")


class LockSkill(BaseSkill):
    intent = "lock"
    description = "Lock the workstation."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "lock"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        if sys.platform != "win32":
            logger.warning("Lock only implemented on Windows")
            return {"status": "error", "message": "Unsupported platform"}
        try:
            import ctypes
            ctypes.windll.user32.LockWorkStation()
            logger.info("Workstation locked")
            return {"status": "ok", "detail": "Workstation locked"}
        except Exception:
            logger.exception("LockSkill failed")
            return {"status": "error", "message": "Lock failed"}


registry.register(LockSkill())