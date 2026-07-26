"""
Privacy controller – microphone, camera, notifications, developer mode, app permissions.
"""

import logging
import subprocess
from typing import Any, Dict

from .base import BaseController
from .registry import registry

logger = logging.getLogger("nova.controllers.privacy")


class PrivacyController(BaseController):
    domain = "privacy"
    description = "Privacy settings (microphone, camera, notifications, developer mode, app permissions)."

    def can_handle(self, intent: Dict[str, Any]) -> bool:
        return intent.get("domain") == self.domain

    def execute(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent.get("operation")
        try:
            if operation == "microphone":
                action = intent.get("action")
                if action == "enable":
                    subprocess.run(["powershell", "-Command", "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone' -Name Value -Value Allow"], check=True)
                    return {"status": "ok", "detail": "Microphone access allowed"}
                if action == "disable":
                    subprocess.run(["powershell", "-Command", "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\microphone' -Name Value -Value Deny"], check=True)
                    return {"status": "ok", "detail": "Microphone access denied"}

            if operation == "camera":
                action = intent.get("action")
                if action == "enable":
                    subprocess.run(["powershell", "-Command", "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\webcam' -Name Value -Value Allow"], check=True)
                    return {"status": "ok", "detail": "Camera access allowed"}
                if action == "disable":
                    subprocess.run(["powershell", "-Command", "Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\CapabilityAccessManager\\ConsentStore\\webcam' -Name Value -Value Deny"], check=True)
                    return {"status": "ok", "detail": "Camera access denied"}

            if operation == "notifications":
                enable = intent.get("enable", True)
                val = 1 if enable else 0
                subprocess.run(["powershell", "-Command", f"Set-ItemProperty -Path 'HKCU:\\Software\\Microsoft\\Windows\\CurrentVersion\\PushNotifications' -Name ToastEnabled -Value {val}"], check=True)
                return {"status": "ok", "detail": f"Notifications {'enabled' if enable else 'disabled'}"}

            if operation == "developer_mode":
                enable = intent.get("enable", True)
                val = 1 if enable else 0
                subprocess.run(["powershell", "-Command", f"Set-ItemProperty -Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\AppModelUnlock' -Name AllowDevelopmentWithoutDevLicense -Value {val}"], check=True)
                return {"status": "ok", "detail": f"Developer mode {'enabled' if enable else 'disabled'}"}

            if operation == "app_permissions":
                # placeholder
                return {"status": "ok", "detail": "App permissions management not yet implemented"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("PrivacyController failed")
            return {"status": "error", "detail": "Privacy operation failed"}


registry.register(PrivacyController())