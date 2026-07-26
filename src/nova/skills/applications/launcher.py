"""
Application launcher skill – open an application by name using the existing AppLauncher.
"""

import logging
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.applications.launcher")


class AppLauncherSkill(BaseSkill):
    intent = "open_application"
    description = "Launch an application by name."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "open_application"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        app_name = intent_data.get("application")
        if not app_name:
            logger.warning("AppLauncherSkill called without application name")
            return {"status": "error", "message": "Missing application name"}

        try:
            from modules.launcher.app_launcher import get_app_launcher

            launcher = get_app_launcher()
            result = launcher.launch(app_name)

            if result.status == "launched":
                logger.info("Launched %s", result.matched_app["name"])
                return {"status": "ok", "detail": f"Launched {result.matched_app['name']}"}
            elif result.status == "ambiguous":
                names = ", ".join(c["name"] for c in result.candidates)
                logger.warning("Ambiguous app name %s: %s", app_name, names)
                return {"status": "ambiguous", "message": result.error_message, "candidates": [c["name"] for c in result.candidates]}
            else:
                logger.warning("App not found: %s", result.error_message)
                return {"status": "error", "message": result.error_message}
        except Exception:
            logger.exception("AppLauncherSkill failed")
            return {"status": "error", "message": "Failed to launch application"}


registry.register(AppLauncherSkill())