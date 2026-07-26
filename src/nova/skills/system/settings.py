"""
Settings skill – generic handler for settings-related intents (e.g., open settings).
"""

import logging
import subprocess
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.settings")


class SettingsSkill(BaseSkill):
    intent = "open_settings"
    description = "Open Windows Settings app."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "open_settings"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            # Open Windows Settings via URI
            subprocess.Popen(["start", "ms-settings:"], shell=True)
            logger.info("Opened Windows Settings")
            return {"status": "ok", "detail": "Settings opened"}
        except Exception:
            logger.exception("SettingsSkill failed")
            return {"status": "error", "message": "Failed to open settings"}


registry.register(SettingsSkill())