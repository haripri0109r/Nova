"""
Brightness skill – set / increase / decrease screen brightness (Windows laptop panels).
"""

import logging
import sys
from typing import Any, Dict, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.brightness")


def _adjust_brightness(delta: int) -> Optional[int]:
    """Adjust brightness by delta, return new brightness or None on failure."""
    if sys.platform != "win32":
        logger.warning("Brightness control only implemented on Windows.")
        return None
    try:
        import wmi
    except ImportError:
        logger.error("wmi package not installed; brightness control unavailable.")
        return None

    c = wmi.WMI(namespace="wmi")
    methods = c.WmiMonitorBrightnessMethods()
    if not methods:
        logger.warning("No WMI brightness methods found (external monitor?).")
        return None
    brightness_objs = c.WmiMonitorBrightness()
    if not brightness_objs:
        logger.warning("Could not read current brightness.")
        return None
    current = brightness_objs[0].CurrentBrightness
    target = max(0, min(100, current + delta))
    try:
        for m in methods:
            m.WmiSetBrightness(target, 0)
        logger.info("Brightness changed from %d%% to %d%%.", current, target)
        return target
    except Exception as e:
        logger.error("Failed to set brightness: %s", e)
        return None


def _set_brightness(level: int) -> bool:
    if sys.platform != "win32":
        logger.warning("Brightness control only implemented on Windows.")
        return False
    try:
        import wmi
    except ImportError:
        logger.error("wmi package not installed; brightness control unavailable.")
        return False

    c = wmi.WMI(namespace="wmi")
    methods = c.WmiMonitorBrightnessMethods()
    if not methods:
        logger.warning("No WMI brightness methods found.")
        return False
    try:
        for m in methods:
            m.WmiSetBrightness(level, 0)
        logger.info("Brightness set to %d%%.", level)
        return True
    except Exception as e:
        logger.error("Failed to set brightness: %s", e)
        return False


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


class BrightnessSkill(BaseSkill):
    intent = "set_brightness"
    description = "Control screen brightness (set, increase, decrease)."

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["set", "increase", "decrease"],
                "description": "Brightness action ('set', 'increase', 'decrease').",
            },
            "level": {
                "type": "integer",
                "description": "Target brightness level (0 to 100) when action is 'set'.",
            },
            "amount": {
                "type": ["integer", "string"],
                "description": "Brightness change amount when action is 'increase' or 'decrease'.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "set_brightness"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        from .display import DisplaySkill
        skill = DisplaySkill()
        return skill.execute(intent_data)


registry.register(BrightnessSkill())