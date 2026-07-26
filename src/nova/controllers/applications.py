"""
Applications controller – launch, close, list running applications.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.applications")


class ApplicationsController(BaseController):
    domain = "applications"
    description = "Launch, close, list running applications."

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        try:
            if operation == "launch":
                name = intent.get("application")
                if not name:
                    return {"status": "error", "detail": "Missing application name"}
                # Use existing AppLauncher via modules.launcher
                try:
                    from modules.launcher.app_launcher import get_app_launcher
                    launcher = get_app_launcher()
                    result = launcher.launch(name)
                    if result.status == "launched":
                        return {"status": "ok", "detail": f"Launched {result.matched_app['name']}"}
                    return {"status": "error", "detail": result.error_message}
                except Exception:
                    # fallback simple start
                    if sys.platform == "win32":
                        subprocess.Popen(["start", "", name], shell=True)
                    return {"status": "ok", "detail": f"Started {name}"}

            if operation == "close":
                name = intent.get("application")
                if not name:
                    return {"status": "error", "detail": "Missing application name"}
                if sys.platform == "win32":
                    subprocess.run(["taskkill", "/IM", f"{name}.exe", "/F"], check=False)
                else:
                    subprocess.run(["pkill", "-f", name], check=False)
                return {"status": "ok", "detail": f"Sent close signal to {name}"}

            if operation == "list":
                # simple list of running processes names
                import psutil
                names = {p.info['name'] for p in psutil.process_iter(['name']) if p.info['name']}
                return {"status": "ok", "detail": sorted(names)}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("ApplicationsController failed")
            return {"status": "error", "detail": "Application operation failed"}


registry.register(ApplicationsController())