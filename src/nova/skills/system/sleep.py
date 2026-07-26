"""
Sleep skill – puts the computer to sleep via rundll32.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.sleep")


class SleepSkill(BaseSkill):
    intent = "sleep"
    description = "Put the computer to sleep."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "sleep"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        if sys.platform != "win32":
            logger.warning("Sleep only implemented on Windows")
            return {"status": "error", "message": "Unsupported platform"}
        try:
            subprocess.run(
                ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
                check=True,
            )
            logger.info("Sleep command issued")
            return {"status": "ok", "detail": "Going to sleep"}
        except Exception:
            logger.exception("SleepSkill failed")
            return {"status": "error", "message": "Sleep failed"}


registry.register(SleepSkill())