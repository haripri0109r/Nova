"""
Bluetooth skill – enable/disable Bluetooth (Windows PowerShell).
"""

import logging
import subprocess
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.bluetooth")


class BluetoothSkill(BaseSkill):
    intent = "bluetooth"
    description = "Enable or disable Bluetooth."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "bluetooth"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action")
        if action not in ("enable", "disable"):
            logger.warning("Unknown bluetooth action: %s", action)
            return {"status": "error", "message": f"Unknown bluetooth action {action}"}

        # PowerShell command to toggle Bluetooth radio
        ps_cmd = (
            "Get-PnpDevice -Class Bluetooth | "
            f"{'Enable-PnpDevice' if action == 'enable' else 'Disable-PnpDevice'} -Confirm:$false"
        )
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                check=True,
                capture_output=True,
                text=True,
            )
            logger.info("Bluetooth %sd", action)
            return {"status": "ok", "detail": f"Bluetooth {action}d"}
        except subprocess.CalledProcessError as e:
            logger.error("Failed to %s Bluetooth: %s", action, e.stderr)
            return {"status": "error", "message": f"Failed to {action} Bluetooth"}
        except Exception:
            logger.exception("BluetoothSkill failed")
            return {"status": "error", "message": "Bluetooth control failed"}


registry.register(BluetoothSkill())