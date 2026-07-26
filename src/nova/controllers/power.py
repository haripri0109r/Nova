"""
Power controller – shutdown, restart, sleep, hibernate, lock, logout, battery saver, performance mode.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.power")


class PowerController(BaseController):
    domain = "power"
    description = "Power operations (shutdown, restart, sleep, hibernate, lock, logout, battery saver, performance mode)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        try:
            if operation == "shutdown":
                if sys.platform == "win32":
                    subprocess.run([r"C:\Windows\System32\shutdown.exe", "/s", "/t", "0"], check=True)
                    return {"status": "ok", "detail": "Shutting down"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "restart":
                if sys.platform == "win32":
                    subprocess.run([r"C:\Windows\System32\shutdown.exe", "/r", "/t", "0"], check=True)
                    return {"status": "ok", "detail": "Restarting"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "sleep":
                if sys.platform == "win32":
                    subprocess.run(["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"], check=True)
                    return {"status": "ok", "detail": "Going to sleep"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "hibernate":
                if sys.platform == "win32":
                    subprocess.run([r"C:\Windows\System32\shutdown.exe", "/h"], check=True)
                    return {"status": "ok", "detail": "Hibernating"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "lock":
                if sys.platform == "win32":
                    import ctypes
                    ctypes.windll.user32.LockWorkStation()
                    return {"status": "ok", "detail": "Workstation locked"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "logout":
                if sys.platform == "win32":
                    subprocess.run(["shutdown", "/l"], check=True)
                    return {"status": "ok", "detail": "Logging out"}
                return {"status": "error", "detail": "Unsupported platform"}

            if operation == "battery_saver":
                enable = intent.get("enable", True)
                # toggle via powercfg
                cmd = "powercfg /setactive SCHEME_MIN" if enable else "powercfg /setactive SCHEME_BALANCED"
                subprocess.run(cmd, shell=True, check=True)
                return {"status": "ok", "detail": f"Battery saver {'enabled' if enable else 'disabled'}"}

            if operation == "performance_mode":
                enable = intent.get("enable", True)
                cmd = "powercfg /setactive SCHEME_MIN" if enable else "powercfg /setactive SCHEME_BALANCED"
                subprocess.run(cmd, shell=True, check=True)
                return {"status": "ok", "detail": f"Performance mode {'enabled' if enable else 'disabled'}"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("PowerController failed")
            return {"status": "error", "detail": "Power operation failed"}


registry.register(PowerController())