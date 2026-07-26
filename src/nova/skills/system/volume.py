"""
Volume skill – set / increase / decrease system volume.
"""

import logging
from typing import Any, Dict, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.volume")


def _get_audio_endpoint():
    """Return the default audio endpoint volume interface."""
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        logger.error("pycaw not installed; volume control unavailable.")
        return None

    devices = AudioUtilities.GetSpeakers()
    if hasattr(devices, "EndpointVolume") and devices.EndpointVolume:
        return devices.EndpointVolume

    try:
        from pycaw.pycaw import IAudioEndpointVolume
        from comtypes import CLSCTX_ALL

        interface = devices._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception as exc:
        logger.error("Failed to get audio endpoint: %s", exc)
        return None


class VolumeSkill(BaseSkill):
    intent = "set_volume"
    description = "Control system volume (set, increase, decrease)."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "set_volume"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action")
        amount = intent_data.get("amount")
        level = intent_data.get("level")

        endpoint = _get_audio_endpoint()
        if endpoint is None:
            return {"status": "error", "message": "Audio endpoint not available"}

        try:
            if action == "set":
                if level is None:
                    return {"status": "error", "message": "Missing level for set action"}
                level = max(0, min(100, int(level)))
                endpoint.SetMasterVolumeLevelScalar(level / 100.0, None)
                logger.info("Volume set to %d%%", level)
                return {"status": "ok", "detail": f"Volume set to {level}%"}

            elif action in ("increase", "decrease"):
                step_map = {"small": 10, "medium": 20, "large": 30}
                step = step_map.get(amount, 10)
                if action == "decrease":
                    step = -step
                # Get current volume
                current_scalar = endpoint.GetMasterVolumeLevelScalar()
                current = int(round(current_scalar * 100))
                target = max(0, min(100, current + step))
                endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
                logger.info("Volume %s by %d%% (now %d%%)", action, abs(step), target)
                return {"status": "ok", "detail": f"Volume {action}d to {target}%"}

            else:
                logger.warning("Unknown volume action: %s", action)
                return {"status": "error", "message": f"Unknown volume action {action}"}

        except Exception:
            logger.exception("VolumeSkill failed")
            return {"status": "error", "message": "Volume control failed"}


registry.register(VolumeSkill())