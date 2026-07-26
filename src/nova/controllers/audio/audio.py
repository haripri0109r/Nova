"""
Audio controller – volume, balance, EQ, spatial audio, default device, per‑app volume, microphone level, mute.
"""

import logging
from typing import Any, Dict, Optional

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.audio")


class AudioController(BaseController):
    intent = "audio"
    description = "Audio settings (volume, balance, EQ, spatial audio, default device, per‑app volume, microphone, mute)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    def _get_endpoint(self):
        try:
            from pycaw.pycaw import AudioUtilities
            devices = AudioUtilities.GetSpeakers()
            if hasattr(devices, "EndpointVolume") and devices.EndpointVolume:
                return devices.EndpointVolume
            from pycaw.pycaw import IAudioEndpointVolume
            from comtypes import CLSCTX_ALL
            interface = devices._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
            return interface.QueryInterface(IAudioEndpointVolume)
        except Exception as e:
            logger.error("Failed to get audio endpoint: %s", e)
            return None

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        action = intent_data.get("action")
        amount = intent_data.get("amount")
        level = intent_data.get("level")

        try:
            if operation == "volume":
                endpoint = self._get_endpoint()
                if not endpoint:
                    return {"status": "error", "detail": "Audio endpoint unavailable"}

                if action == "set":
                    if level is None:
                        return {"status": "error", "detail": "Missing level"}
                    level = max(0, min(100, int(level)))
                    endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
                    return {"status": "ok", "detail": f"Volume set to {level}%"}

                if action in ("increase", "decrease"):
                    step_map = {"small": 10, "medium": 20, "large": 30}
                    step = step_map.get(amount, 10)
                    if action == "decrease":
                        step = -step
                    current = int(round(endpoint.GetMasterVolumeLevelScalar() * 100))
                    target = max(0, min(100, current + step))
                    endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
                    return {"status": "ok", "detail": f"Volume {action}d to {target}%"}

                if action == "mute":
                    endpoint.SetMute(1, None)
                    return {"status": "ok", "detail": "Muted"}
                if action == "unmute":
                    endpoint.SetMute(0, None)
                    return {"status": "ok", "detail": "Unmuted"}

            if operation == "balance":
                # Not directly supported by pycaw simple API; placeholder
                return {"status": "error", "detail": "Balance control not implemented"}

            if operation == "default_device":
                # placeholder
                return {"status": "error", "detail": "Default device change not implemented"}

            if operation == "per_app_volume":
                # placeholder
                return {"status": "error", "detail": "Per‑app volume not implemented"}

            if operation == "microphone":
                # placeholder
                return {"status": "error", "detail": "Microphone control not implemented"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("AudioController failed")
            return {"status": "error", "detail": "Audio operation failed"}