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


class BrightnessSkill(BaseSkill):
    intent = "set_brightness"
    description = "Control screen brightness (set, increase, decrease)."

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "set_brightness"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action")
        amount = intent_data.get("amount")
        level = intent_data.get("level")

        try:
            if action == "set":
                if level is None:
                    return {"status": "error", "message": "Missing level for set action"}
                level = max(0, min(100, int(level)))
                ok = _set_brightness(level)
                if ok:
                    logger.info("Brightness set to %d%%", level)
                    return {"status": "ok", "detail": f"Brightness set to {level}%"}
                else:
                    return {"status": "error", "message": "Failed to set brightness"}

            elif action in ("increase", "decrease"):
                step_map = {"small": 10, "medium": 20, "large": 30}
                step = step_map.get(amount, 10)
                if action == "decrease":
                    step = -step
                new_level = _adjust_brightness(step)
                if new_level is not None:
                    logger.info("Brightness %s by %d%% (now %d%%)", action, abs(step), new_level)
                    return {"status": "ok", "detail": f"Brightness {action}d to {new_level}%"}
                else:
                    return {"status": "error", "message": "Failed to adjust brightness"}

            else:
                logger.warning("Unknown brightness action: %s", action)
                return {"status": "error", "message": f"Unknown brightness action {action}"}

        except Exception:
            logger.exception("BrightnessSkill failed")
            return {"status": "error", "message": "Brightness control failed"}


registry.register(BrightnessSkill())