"""
Applications controller – launch, close, list running apps.
"""

import logging
import psutil
import subprocess
import sys
from typing import Any, Dict, List

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.applications")


class ApplicationsController(BaseController):
    intent = "applications"
    description = "Application lifecycle (launch, close, list running)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        app_name = intent_data.get("application")

        try:
            if operation == "launch":
                if not app_name:
                    return {"status": "error", "detail": "Missing application name"}
                # Use existing AppLauncher for fuzzy matching
                from modules.launcher.app_launcher import get_app_launcher
                launcher = get_app_launcher()
                result = launcher.launch(app_name)
                if result.status == "launched":
                    return {"status": "ok", "detail": f"Launched {result.matched_app['name']}"}
                return {"status": "error", "detail": result.error_message}

            if operation == "close":
                if not app_name:
                    return {"status": "error", "detail": "Missing application name"}
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/IM", f"{app_name}.exe", "/F"], check=False)
                else:
                    subprocess.run(["pkill", "-f", app_name], check=False)
                return {"status": "ok", "detail": f"Close signal sent to {app_name}"}

            if operation == "list":
                apps: List[Dict[str, Any]] = []
                for proc in psutil.process_iter(["pid", "name", "username"]):
                    try:
                        apps.append(proc.info)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                return {"status": "ok", "detail": apps[:50]}  # limit

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("ApplicationsController failed")
            return {"status": "error", "detail": "Application operation failed"}