"""
Display controller – handles brightness, resolution, refresh rate, HDR, scaling, orientation, night light, adaptive brightness.
"""

import logging
import sys
from typing import Any, Dict, Optional

from nova.controllers.base import BaseController
from nova.controllers.registry import registry

logger = logging.getLogger("nova.controllers.display")


class DisplayController(BaseController):
    intent = "display"
    description = "Display settings (brightness, resolution, refresh rate, HDR, scaling, orientation, night light, adaptive brightness)."

    def __init__(self) -> None:
        super().__init__()
        registry.register(self)

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.intent

    # ----- internal helpers -------------------------------------------------
    def _adjust_brightness(self, delta: int) -> Optional[int]:
        if sys.platform != "win32":
            logger.warning("Brightness control only on Windows")
            return None
        try:
            import wmi
        except ImportError:
            logger.error("wmi not installed")
            return None
        c = wmi.WMI(namespace="wmi")
        methods = c.WmiMonitorBrightnessMethods()
        if not methods:
            return None
        brightness_objs = c.WmiMonitorBrightness()
        if not brightness_objs:
            return None
        current = brightness_objs[0].CurrentBrightness
        target = max(0, min(100, current + delta))
        try:
            for m in methods:
                m.WmiSetBrightness(target, 0)
            logger.info("Brightness %d -> %d", current, target)
            return target
        except Exception as e:
            logger.error("Failed to set brightness: %s", e)
            return None

    def _set_brightness(self, level: int) -> bool:
        if sys.platform != "win32":
            return False
        try:
            import wmi
        except ImportError:
            return False
        c = wmi.WMI(namespace="wmi")
        methods = c.WmiMonitorBrightnessMethods()
        if not methods:
            return False
        try:
            for m in methods:
                m.WmiSetBrightness(level, 0)
            logger.info("Brightness set to %d", level)
            return True
        except Exception as e:
            logger.error("Failed to set brightness: %s", e)
            return False

    # ------------------------------------------------------------------------
    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        operation = intent_data.get("operation")
        action = intent_data.get("action")
        amount = intent_data.get("amount")
        level = intent_data.get("level")

        try:
            if operation == "brightness":
                if action == "set":
                    if level is None:
                        return {"status": "error", "detail": "Missing level"}
                    level = max(0, min(100, int(level)))
                    ok = self._set_brightness(level)
                    return {"status": "ok" if ok else "error",
                            "detail": f"Brightness set to {level}%" if ok else "Failed to set brightness"}
                if action in ("increase", "decrease"):
                    step_map = {"small": 10, "medium": 20, "large": 30}
                    step = step_map.get(amount, 10)
                    if action == "decrease":
                        step = -step
                    new_level = self._adjust_brightness(step)
                    if new_level is not None:
                        return {"status": "ok", "detail": f"Brightness {action}d to {new_level}%"}
                    return {"status": "error", "detail": "Failed to adjust brightness"}
                return {"status": "error", "detail": f"Unknown action {action}"}

            # placeholders for other operations
            if operation in ("resolution", "refresh_rate", "hdr", "scaling", "orientation", "night_light", "adaptive_brightness"):
                logger.info("Operation %s not yet implemented", operation)
                return {"status": "error", "detail": f"{operation} not implemented yet"}

            return {"status": "error", "detail": f"Unknown operation {operation}"}
        except Exception:
            logger.exception("DisplayController failed")
            return {"status": "error", "detail": "Display operation failed"}