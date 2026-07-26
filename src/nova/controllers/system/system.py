"""
System controller – handles power related intents.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.system")


class SystemController(BaseController):
    intent = "system"
    description = "System power operations (shutdown, restart, sleep, lock)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        if not operation:
            return {"status": "error", "detail": "Missing operation"}

        try:
            if operation == "shutdown":
                if sys.platform == "win32":
                    subprocess.run(
                        [r"C:\Windows\System32\shutdown.exe", "/s", "/t", "0"],
                        check=True,
                    )
                    return {"status": "ok", "detail": "Shutting down"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "restart":
                if sys.platform == "win32":
                    subprocess.run(
                        [r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"],
                        check=True,
                    )
                    return {"status": "ok", "detail": "Restarting"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "sleep":
                if sys.platform == "win32":
                    subprocess.run(
                        ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
                        check=True,
                    )
                    return {"status": "ok", "detail": "Going to sleep"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "lock":
                if sys.platform == "win32":
                    import ctypes
                    ctypes.windll.user32.LockWorkStation()
                    return {"status": "ok", "detail": "Workstation locked"}
                return {"status": "error", "detail": "Unsupported platform"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("SystemController failed")
            return {"status": "error", "detail": "System operation failed"}