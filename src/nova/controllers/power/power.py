"""
Power controller – shutdown, restart, sleep, hibernate, lock, logout, battery saver, performance mode.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.power")


class PowerController(BaseController):
    intent = "power"
    description = "Power management (shutdown, restart, sleep, hibernate, lock, logout, battery saver, performance mode)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")

        try:
            if operation == "shutdown":
                subprocess.run([r"C:\Windows\System32\shutdown.exe", "/s", "/t", "0"], check=True)
                return {"status": "ok", "detail": "Shutting down"}

            if operation == "restart":
                subprocess.run([r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"], check=True)
                return {"status": "ok", "detail": "Restarting"}

            if operation == "sleep":
                subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], check=True)
                return {"status": "ok", "detail": "Going to sleep"}

            if operation == "hibernate":
                subprocess.run([r"C:\Windows\System32\shutdown.exe", "/h"], check=True)
                return {"status": "ok", "detail": "Hibernating"}

            if operation == "lock":
                import ctypes
                ctypes.windll.user32.LockWorkStation()
                return {"status": "ok", "detail": "Workstation locked"}

            if operation == "logout":
                subprocess.run(["shutdown", "/l"], check=True)
                return {"status": "ok", "detail": "Logging out"}

            if operation == "battery_saver":
                # Not directly scriptable; placeholder
                return {"status": "error", "detail": "Battery saver control not implemented"}

            if operation == "performance_mode":
                return {"status": "error", "detail": "Performance mode not implemented"}

            return {"status": "error", "detail": f"Unknown power operation {operation}"}
        except Exception:
            logger.exception("PowerController failed")
            return {"status": "error", "detail": "Power operation failed"}