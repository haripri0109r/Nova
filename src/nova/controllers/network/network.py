"""
Network controller – Wi‑Fi, Ethernet, VPN, Bluetooth, Airplane mode, Hotspot, Data usage, Proxy, DNS, Adapter options.
"""

import logging
import subprocess
import sys
from typing import Any, Dict

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.network")


class NetworkController(BaseController):
    intent = "network"
    description = "Network settings (Wi‑Fi, Ethernet, VPN, Bluetooth, Airplane mode, Hotspot, Data usage, Proxy, DNS)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        action = intent_data.get("action")

        try:
            if operation == "wifi":
                if action == "enable":
                    subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", "enable"], check=True)
                    return {"status": "ok", "detail": "Wi‑Fi enabled"}
                if action == "disable":
                    subprocess.run(["netsh", "interface", "set", "interface", "Wi-Fi", "disable"], check=True)
                    return {"status": "ok", "detail": "Wi‑Fi disabled"}
                return {"status": "error", "detail": f"Unknown wifi action {action}"}

            if operation == "ethernet":
                if action == "enable":
                    subprocess.run(["netsh", "interface", "set", "interface", "Ethernet", "enable"], check=True)
                    return {"status": "ok", "detail": "Ethernet enabled"}
                if action == "disable":
                    subprocess.run(["netsh", "interface", "set", "interface", "Ethernet", "disable"], check=True)
                    return {"status": "ok", "detail": "Ethernet disabled"}
                return {"status": "error", "detail": f"Unknown ethernet action {action}"}

            if operation == "bluetooth":
                if sys.platform != "win32":
                    return {"status": "error", "detail": "Bluetooth control only on Windows"}
                ps_cmd = (
                    "Get-PnpDevice -Class Bluetooth | "
                    f"{'Enable-PnpDevice' if action == 'enable' else 'Disable-PnpDevice'} -Confirm:$false"
                )
                subprocess.run(["powershell", "-NoProfile", "-Command", ps_cmd], check=True)
                return {"status": "ok", "detail": f"Bluetooth {action}d"}

            if operation == "airplane_mode":
                # Toggle airplane mode via registry / netsh not straightforward; placeholder
                return {"status": "error", "detail": "Airplane mode not implemented"}

            if operation == "vpn":
                return {"status": "error", "detail": "VPN control not implemented"}

            if operation == "hotspot":
                return {"status": "error", "detail": "Hotspot not implemented"}

            if operation == "dns":
                return {"status": "error", "detail": "DNS settings not implemented"}

            if operation == "proxy":
                return {"status": "error", "detail": "Proxy settings not implemented"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("NetworkController failed")
            return {"status": "error", "detail": "Network operation failed"}