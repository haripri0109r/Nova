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


def _parse_step_amount(amount: Any, default: int = 10) -> int:
    if amount is None:
        return default
    step_map = {"small": 10, "medium": 20, "large": 30}
    if isinstance(amount, str):
        lower = amount.lower().strip()
        if lower in step_map:
            return step_map[lower]
        try:
            return int(lower)
        except ValueError:
            return default
    elif isinstance(amount, (int, float)):
        return int(amount)
    return default


class VolumeSkill(BaseSkill):
    intent = "set_volume"
    description = "Control system volume (set, increase, decrease, mute, unmute)."

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "increase", "decrease", "mute", "unmute"],
                "description": "Volume action ('set', 'increase', 'decrease', 'mute', 'unmute').",
            },
            "level": {
                "type": "integer",
                "description": "Target volume level (0 to 100) when action is 'set'.",
            },
            "amount": {
                "type": ["integer", "string"],
                "description": "Volume change amount when action is 'increase' or 'decrease'.",
            },
        },
        "required": ["action"],
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "set_volume"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        from .audio import AudioSkill
        skill = AudioSkill()
        return skill.execute(intent_data)


registry.register(VolumeSkill())