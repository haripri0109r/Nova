"""
Windows controller – launch built-in tools (settings, task manager, control panel, registry, services, device manager, cmd, powershell, explorer).
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.windows")


class WindowsController(BaseController):
    domain = "windows"
    description = "Built‑in Windows utilities."

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        try:
            if operation == "settings":
                subprocess.Popen(["start", "ms-settings:"], shell=True)
                return {"status": "ok", "detail": "Opened Settings"}

            if operation == "task_manager":
                subprocess.Popen(["taskmgr"])
                return {"status": "ok", "detail": "Opened Task Manager"}

            if operation == "control_panel":
                subprocess.Popen(["control"])
                return {"status": "ok", "detail": "Opened Control Panel"}

            if operation == "registry":
                subprocess.Popen(["regedit"])
                return {"status": "ok", "detail": "Opened Registry Editor"}

            if operation == "services":
                subprocess.Popen(["services.msc"])
                return {"status": "ok", "detail": "Opened Services"}

            if operation == "device_manager":
                subprocess.Popen(["devmgmt.msc"])
                return {"status": "ok", "detail": "Opened Device Manager"}

            if operation == "cmd":
                subprocess.Popen(["cmd.exe"])
                return {"status": "ok", "detail": "Opened Command Prompt"}

            if operation == "powershell":
                subprocess.Popen(["powershell.exe"])
                return {"status": "ok", "detail": "Opened PowerShell"}

            if operation == "explorer":
                subprocess.Popen(["explorer.exe"])
                return {"status": "ok", "detail": "Opened File Explorer"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("WindowsController failed")
            return {"status": "error", "detail": "Windows operation failed"}


registry.register(WindowsController())