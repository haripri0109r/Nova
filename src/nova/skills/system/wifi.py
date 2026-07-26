"""
Wi‑Fi skill – enable/disable Wi‑Fi (Windows netsh).
"""

import logging
import subprocess
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.wifi")


class WifiSkill(BaseSkill):
    intent = "wifi"
    description = "Enable or disable Wi‑Fi."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "wifi"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action")
        if action not in ("enable", "disable"):
            logger.warning("Unknown wifi action: %s", action)
            return {"status": "error", "message": f"Unknown wifi action {action}"}

        try:
            if action == "enable":
                subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", "enable"], check=True)
                logger.info("Wi‑Fi enabled")
                return {"status": "ok", "detail": "Wi‑Fi enabled"}
            else:
                subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", "disable"], check=True)
                logger.info("Wi‑Fi disabled")
                return {"status": "ok", "detail": "Wi‑Fi disabled"}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to %s Wi‑Fi: %s", action, e)
            return {"status": "error", "message": f"Failed to {action} Wi‑Fi"}
        except Exception:
            logger.exception("WifiSkill failed")
            return {"status": "error", "message": "Wi‑Fi control failed"}


registry.register(WifiSkill())