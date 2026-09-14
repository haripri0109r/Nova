"""
Display skill – control screen brightness, query display information,
validate/mutate display resolution, refresh rate, and orientation,
and safely handle Night Light.
"""

import ctypes
from ctypes import wintypes
import logging
import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.display")

# Win32 Constants
ENUM_CURRENT_SETTINGS = -1
ENUM_REGISTRY_SETTINGS = -2

DM_ORIENTATION = 0x00000001
DM_DISPLAYORIENTATION = 0x00000080
DM_PELSWIDTH = 0x00080000
DM_PELSHEIGHT = 0x00100000
DM_DISPLAYFLAGS = 0x00200000
DM_DISPLAYFREQUENCY = 0x00400000

CDS_UPDATEREGISTRY = 0x00000001
CDS_TEST = 0x00000002
CDS_FULLSCREEN = 0x00000004
CDS_GLOBAL = 0x00000008
CDS_SET_PRIMARY = 0x00000010
CDS_RESET = 0x40000000

DISP_CHANGE_SUCCESSFUL = 0
DISP_CHANGE_RESTART = 1
DISP_CHANGE_FAILED = -1
DISP_CHANGE_BADMODE = -2
DISP_CHANGE_NOTUPDATED = -3
DISP_CHANGE_BADFLAGS = -4
DISP_CHANGE_BADPARAM = -5

SM_CXSCREEN = 0
SM_CYSCREEN = 1
SM_CMONITORS = 80

DISPLAY_DEVICE_ATTACHED_TO_DESKTOP = 0x00000001
DISPLAY_DEVICE_PRIMARY_DEVICE = 0x00000004

ORIENTATION_MAP = {
    0: "landscape",
    1: "portrait",
    2: "landscape_flipped",
    3: "portrait_flipped",
}
ORIENTATION_REVERSE_MAP = {v: k for k, v in ORIENTATION_MAP.items()}


# =============================================================================
# Accurate Win32 Structures
# =============================================================================

class POINTL(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class _DEVMODE_UNION(ctypes.Union):
    class _PRINTER(ctypes.Structure):
        _fields_ = [
            ("dmOrientation", ctypes.c_short),
            ("dmPaperSize", ctypes.c_short),
            ("dmPaperLength", ctypes.c_short),
            ("dmPaperWidth", ctypes.c_short),
            ("dmScale", ctypes.c_short),
            ("dmCopies", ctypes.c_short),
            ("dmDefaultSource", ctypes.c_short),
            ("dmPrintQuality", ctypes.c_short),
        ]

    class _DISPLAY(ctypes.Structure):
        _fields_ = [
            ("dmPosition", POINTL),
            ("dmDisplayOrientation", wintypes.DWORD),
            ("dmDisplayFixedOutput", wintypes.DWORD),
        ]

    _anonymous_ = ("_display",)
    _fields_ = [
        ("_printer", _PRINTER),
        ("_display", _DISPLAY),
    ]


class DEVMODEW(ctypes.Structure):
    _anonymous_ = ("_u",)
    _fields_ = [
        ("dmDeviceName", wintypes.WCHAR * 32),
        ("dmSpecVersion", wintypes.WORD),
        ("dmDriverVersion", wintypes.WORD),
        ("dmSize", wintypes.WORD),
        ("dmDriverExtra", wintypes.WORD),
        ("dmFields", wintypes.DWORD),
        ("_u", _DEVMODE_UNION),
        ("dmColor", ctypes.c_short),
        ("dmDuplex", ctypes.c_short),
        ("dmYResolution", ctypes.c_short),
        ("dmTTOption", ctypes.c_short),
        ("dmCollate", ctypes.c_short),
        ("dmFormName", wintypes.WCHAR * 32),
        ("dmLogPixels", wintypes.WORD),
        ("dmBitsPerPel", wintypes.DWORD),
        ("dmPelsWidth", wintypes.DWORD),
        ("dmPelsHeight", wintypes.DWORD),
        ("dmDisplayFlags", wintypes.DWORD),
        ("dmDisplayFrequency", wintypes.DWORD),
        ("dmICMMethod", wintypes.DWORD),
        ("dmICMIntent", wintypes.DWORD),
        ("dmMediaType", wintypes.DWORD),
        ("dmDitherType", wintypes.DWORD),
        ("dmReserved1", wintypes.DWORD),
        ("dmReserved2", wintypes.DWORD),
        ("dmPanningWidth", wintypes.DWORD),
        ("dmPanningHeight", wintypes.DWORD),
    ]


class DISPLAY_DEVICEW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("DeviceName", wintypes.WCHAR * 32),
        ("DeviceString", wintypes.WCHAR * 128),
        ("StateFlags", wintypes.DWORD),
        ("DeviceID", wintypes.WCHAR * 128),
        ("DeviceKey", wintypes.WCHAR * 128),
    ]


# =============================================================================
# Helper Functions
# =============================================================================

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


def _get_wmi_monitor():
    """Return (methods, brightness_objs) from WMI namespace 'wmi', or (None, None)."""
    if sys.platform != "win32":
        return None, None
    try:
        import wmi
    except ImportError:
        logger.error("wmi package not installed; brightness control unavailable.")
        return None, None

    try:
        c = wmi.WMI(namespace="wmi")
        methods = c.WmiMonitorBrightnessMethods()
        brightness_objs = c.WmiMonitorBrightness()
        return methods, brightness_objs
    except Exception as exc:
        logger.debug("WMI monitor query failed: %s", exc)
        return None, None


def _get_active_display_devices() -> List[Dict[str, Any]]:
    """Enumerate display devices attached to the Windows desktop."""
    if sys.platform != "win32":
        return []
    devices = []
    user32 = ctypes.windll.user32
    i = 0
    while True:
        dd = DISPLAY_DEVICEW()
        dd.cb = ctypes.sizeof(DISPLAY_DEVICEW)
        if not user32.EnumDisplayDevicesW(None, i, ctypes.byref(dd), 0):
            break
        if dd.StateFlags & DISPLAY_DEVICE_ATTACHED_TO_DESKTOP:
            is_primary = bool(dd.StateFlags & DISPLAY_DEVICE_PRIMARY_DEVICE)
            devices.append({
                "device_name": dd.DeviceName,
                "adapter_string": dd.DeviceString,
                "is_primary": is_primary,
                "device_id": dd.DeviceID,
            })
        i += 1
    return devices


def _get_supported_modes(device_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Enumerate all supported display modes for a given display device."""
    if sys.platform != "win32":
        return []
    user32 = ctypes.windll.user32
    modes = []
    seen = set()
    i = 0
    while True:
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(device_name, i, ctypes.byref(dm)):
            break
        key = (dm.dmPelsWidth, dm.dmPelsHeight, dm.dmDisplayFrequency, dm.dmBitsPerPel)
        if key not in seen:
            seen.add(key)
            modes.append({
                "width": int(dm.dmPelsWidth),
                "height": int(dm.dmPelsHeight),
                "refresh_rate": int(dm.dmDisplayFrequency),
                "bits_per_pixel": int(dm.dmBitsPerPel),
            })
        i += 1
    return modes


# =============================================================================
# DisplaySkill Implementation
# =============================================================================

class DisplaySkill(BaseSkill):
    """
    Canonical Windows Display Control Skill.
    Controls screen brightness, queries display metadata, validates and changes
    display resolution, refresh rate, and orientation, and provides honest Night Light navigation.
    """
    intent = "display"
    description = "Control Windows display (brightness, display info, resolution, refresh rate, orientation, night light)."

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_brightness",
                    "set_brightness",
                    "increase_brightness",
                    "decrease_brightness",
                    "get_display_info",
                    "get_resolution",
                    "set_resolution",
                    "get_refresh_rate",
                    "set_refresh_rate",
                    "get_orientation",
                    "set_orientation",
                    "night_light",
                ],
                "description": "Display action to perform.",
            },
            "level": {
                "type": "integer",
                "description": "Target brightness level (0 to 100) when setting brightness.",
            },
            "amount": {
                "type": ["integer", "string"],
                "description": "Brightness change amount or step ('small', 'medium', 'large').",
            },
            "width": {
                "type": "integer",
                "description": "Screen width in pixels for resolution change.",
            },
            "height": {
                "type": "integer",
                "description": "Screen height in pixels for resolution change.",
            },
            "refresh_rate": {
                "type": "integer",
                "description": "Target refresh rate in Hz.",
            },
            "orientation": {
                "type": "string",
                "enum": ["landscape", "portrait", "landscape_flipped", "portrait_flipped"],
                "description": "Target screen orientation.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def validate(self, parameters: Dict[str, Any]) -> bool:
        """Validate input parameters against canonical schema."""
        if not isinstance(parameters, dict):
            raise ValueError("Parameters must be a dictionary")
        if "action" not in parameters:
            raise ValueError("DisplaySkill: missing required 'action' parameter")
        action = parameters.get("action")
        valid_actions = self.parameters_schema["properties"]["action"]["enum"]
        if action not in valid_actions:
            raise ValueError(f"DisplaySkill: invalid action '{action}'. Must be one of {valid_actions}")

        allowed_keys = set(self.parameters_schema["properties"].keys())
        for k in parameters:
            if k not in allowed_keys:
                raise ValueError(f"DisplaySkill: Unexpected parameter '{k}' (additional properties not allowed)")

        if action == "set_brightness":
            if "level" not in parameters:
                raise ValueError("DisplaySkill: 'set_brightness' requires 'level' parameter")
            level = parameters.get("level")
            if not isinstance(level, (int, float)):
                raise ValueError(f"DisplaySkill: 'level' must be an integer, got {type(level).__name__}")
            if int(level) < 0 or int(level) > 100:
                raise ValueError(f"DisplaySkill: 'level' must be between 0 and 100, got {level}")

        elif action == "set_resolution":
            if "width" not in parameters or "height" not in parameters:
                raise ValueError("DisplaySkill: 'set_resolution' requires both 'width' and 'height' parameters")
            if not isinstance(parameters.get("width"), int) or not isinstance(parameters.get("height"), int):
                raise ValueError("DisplaySkill: 'width' and 'height' must be integers")
            if parameters["width"] <= 0 or parameters["height"] <= 0:
                raise ValueError("DisplaySkill: 'width' and 'height' must be positive integers")

        elif action == "set_refresh_rate":
            if "refresh_rate" not in parameters:
                raise ValueError("DisplaySkill: 'set_refresh_rate' requires 'refresh_rate' parameter")
            if not isinstance(parameters.get("refresh_rate"), int) or parameters["refresh_rate"] <= 0:
                raise ValueError("DisplaySkill: 'refresh_rate' must be a positive integer")

        elif action == "set_orientation":
            if "orientation" not in parameters:
                raise ValueError("DisplaySkill: 'set_orientation' requires 'orientation' parameter")
            orient = parameters.get("orientation")
            valid_orients = self.parameters_schema["properties"]["orientation"]["enum"]
            if orient not in valid_orients:
                raise ValueError(f"DisplaySkill: invalid orientation '{orient}'. Must be one of {valid_orients}")

        return True

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("display", "set_brightness", "brightness", "display_control")

    # -------------------------------------------------------------------------
    # Brightness Handlers
    # -------------------------------------------------------------------------

    def _get_brightness(self) -> Dict[str, Any]:
        """Read current brightness using WMI."""
        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Brightness control is only implemented on Windows.",
                "detail": "Brightness control is only implemented on Windows.",
            }

        methods, brightness_objs = _get_wmi_monitor()
        if not methods or not brightness_objs:
            return {
                "status": "unsupported",
                "message": "Hardware or external monitor does not support WMI brightness control.",
                "detail": "No WMI monitor brightness methods found. External monitors or desktop displays require DDC/CI or physical monitor controls.",
            }

        try:
            current = int(brightness_objs[0].CurrentBrightness)
            return {
                "status": "ok",
                "action": "get_brightness",
                "brightness": current,
                "message": f"Current brightness is {current}%.",
                "detail": f"Current brightness is {current}%.",
            }
        except Exception as exc:
            logger.exception("Failed to read brightness: %s", exc)
            return {"status": "error", "message": f"Failed to read brightness: {exc}"}

    def _set_brightness(self, level: int) -> Dict[str, Any]:
        """Set brightness to target level (0-100) with read-back verification."""
        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Brightness control is only implemented on Windows.",
                "detail": "Brightness control is only implemented on Windows.",
            }

        target = max(0, min(100, int(level)))
        methods, brightness_objs = _get_wmi_monitor()
        if not methods:
            return {
                "status": "unsupported",
                "message": "Hardware or external monitor does not support WMI brightness control.",
                "detail": "No WMI monitor brightness methods found. External monitors require physical controls.",
            }

        try:
            for m in methods:
                m.WmiSetBrightness(target, 0)
            
            # Read-back verification
            _, verify_objs = _get_wmi_monitor()
            verified = None
            if verify_objs:
                verified = int(verify_objs[0].CurrentBrightness)

            msg = f"Brightness set to {target}%."
            if verified is not None:
                msg = f"Brightness set to {verified}% (verified)."

            return {
                "status": "ok",
                "action": "set_brightness",
                "brightness": verified if verified is not None else target,
                "verified": verified == target if verified is not None else False,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to set brightness: %s", exc)
            return {"status": "error", "message": f"Failed to set brightness: {exc}"}

    def _adjust_brightness(self, delta: int) -> Dict[str, Any]:
        """Adjust brightness by delta with read-back verification."""
        read_res = self._get_brightness()
        if read_res.get("status") != "ok":
            return read_res

        current = read_res["brightness"]
        target = max(0, min(100, current + delta))
        set_res = self._set_brightness(target)
        if set_res.get("status") == "ok":
            action_word = "increased" if delta > 0 else "decreased"
            set_res["action"] = f"{action_word}_brightness"
            set_res["delta"] = delta
            set_res["message"] = f"Brightness {action_word} by {abs(delta)}% (now {set_res['brightness']}%)."
            set_res["detail"] = set_res["message"]
        return set_res

    # -------------------------------------------------------------------------
    # Display Information Handlers
    # -------------------------------------------------------------------------

    def _get_display_info(self) -> Dict[str, Any]:
        """Query display count, primary display, resolution, refresh rate, and orientation."""
        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Display info query is only implemented on Windows.",
                "detail": "Display info query is only implemented on Windows.",
            }

        try:
            user32 = ctypes.windll.user32
            monitor_count = int(user32.GetSystemMetrics(SM_CMONITORS))
            if monitor_count == 0:
                monitor_count = 1

            dm = DEVMODEW()
            dm.dmSize = ctypes.sizeof(DEVMODEW)
            res = user32.EnumDisplaySettingsW(None, ENUM_CURRENT_SETTINGS, ctypes.byref(dm))
            if not res:
                return {"status": "error", "message": "Failed to read display settings via EnumDisplaySettingsW."}

            width = int(dm.dmPelsWidth)
            height = int(dm.dmPelsHeight)
            freq = int(dm.dmDisplayFrequency)
            orient_code = int(dm.dmDisplayOrientation)
            orient_str = ORIENTATION_MAP.get(orient_code, "unknown")
            bpp = int(dm.dmBitsPerPel)

            devices = _get_active_display_devices()
            primary_dev = next((d for d in devices if d.get("is_primary")), devices[0] if devices else None)
            dev_name = primary_dev["device_name"] if primary_dev else "Default Display"
            adapter_name = primary_dev["adapter_string"] if primary_dev else "Standard Display Adapter"

            msg = f"Display: {width}x{height} @ {freq}Hz ({orient_str}), {monitor_count} monitor(s) detected."
            return {
                "status": "ok",
                "action": "get_display_info",
                "monitor_count": monitor_count,
                "primary_display": {
                    "device_name": dev_name,
                    "adapter": adapter_name,
                    "width": width,
                    "height": height,
                    "refresh_rate": freq,
                    "orientation": orient_str,
                    "bits_per_pixel": bpp,
                },
                "displays": devices,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to query display info: %s", exc)
            return {"status": "error", "message": f"Failed to query display info: {exc}"}

    # -------------------------------------------------------------------------
    # Resolution, Refresh Rate, and Orientation Handlers
    # -------------------------------------------------------------------------

    def _set_resolution(self, width: int, height: int) -> Dict[str, Any]:
        """Validate and apply display resolution using Win32 ChangeDisplaySettingsExW."""
        if sys.platform != "win32":
            return {"status": "unsupported", "message": "Resolution control is only implemented on Windows."}

        devices = _get_active_display_devices()
        primary_dev = next((d for d in devices if d.get("is_primary")), devices[0] if devices else None)
        dev_name = primary_dev["device_name"] if primary_dev else None

        # 1. Validate requested resolution against supported modes
        supported_modes = _get_supported_modes(dev_name)
        supported_res = {(m["width"], m["height"]) for m in supported_modes}
        if (width, height) not in supported_res:
            avail_str = ", ".join(f"{w}x{h}" for w, h in sorted(supported_res)[:8])
            return {
                "status": "unsupported",
                "message": f"Resolution {width}x{height} is not supported by the display. Supported resolutions include: {avail_str}...",
                "detail": f"Resolution {width}x{height} not in enumerated modes.",
                "supported_resolutions": sorted(list(supported_res)),
            }

        user32 = ctypes.windll.user32
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(dev_name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            return {"status": "error", "message": "Failed to read current display settings."}

        dm.dmPelsWidth = width
        dm.dmPelsHeight = height
        dm.dmFields = DM_PELSWIDTH | DM_PELSHEIGHT

        # 2. Call ChangeDisplaySettingsExW with CDS_TEST first
        test_res = user32.ChangeDisplaySettingsExW(dev_name, ctypes.byref(dm), None, CDS_TEST, None)
        if test_res != DISP_CHANGE_SUCCESSFUL:
            logger.warning("ChangeDisplaySettingsExW CDS_TEST failed with code %d", test_res)
            # Provide honest failure and offer/navigate to Settings
            try:
                os.startfile("ms-settings:display")
            except Exception:
                pass
            msg = (
                f"Windows display driver rejected direct resolution change to {width}x{height} (CDS_TEST code {test_res}). "
                "The display driver or system policy restricts direct mode mutations on this panel. "
                "Opened Windows Display Settings for manual selection."
            )
            return {
                "status": "restricted",
                "action": "navigated",
                "target_uri": "ms-settings:display",
                "test_code": test_res,
                "message": msg,
                "detail": msg,
            }

        # 3. Apply change
        apply_res = user32.ChangeDisplaySettingsExW(dev_name, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
        if apply_res != DISP_CHANGE_SUCCESSFUL:
            return {"status": "error", "message": f"Failed to apply resolution change: error code {apply_res}"}

        # 4. Read back and verify
        verify_dm = DEVMODEW()
        verify_dm.dmSize = ctypes.sizeof(DEVMODEW)
        user32.EnumDisplaySettingsW(dev_name, ENUM_CURRENT_SETTINGS, ctypes.byref(verify_dm))
        actual_w = int(verify_dm.dmPelsWidth)
        actual_h = int(verify_dm.dmPelsHeight)

        if actual_w == width and actual_h == height:
            msg = f"Display resolution successfully changed to {width}x{height}."
            return {
                "status": "ok",
                "action": "set_resolution",
                "width": actual_w,
                "height": actual_h,
                "verified": True,
                "message": msg,
                "detail": msg,
            }
        else:
            return {
                "status": "failed",
                "message": f"Resolution verification failed: active resolution is {actual_w}x{actual_h}, expected {width}x{height}.",
            }

    def _set_refresh_rate(self, refresh_rate: int) -> Dict[str, Any]:
        """Validate and apply display refresh rate using Win32 ChangeDisplaySettingsExW."""
        if sys.platform != "win32":
            return {"status": "unsupported", "message": "Refresh rate control is only implemented on Windows."}

        devices = _get_active_display_devices()
        primary_dev = next((d for d in devices if d.get("is_primary")), devices[0] if devices else None)
        dev_name = primary_dev["device_name"] if primary_dev else None

        supported_modes = _get_supported_modes(dev_name)
        supported_freqs = {m["refresh_rate"] for m in supported_modes}
        if refresh_rate not in supported_freqs:
            avail_str = ", ".join(f"{f}Hz" for f in sorted(supported_freqs))
            return {
                "status": "unsupported",
                "message": f"Refresh rate {refresh_rate}Hz is not supported by the display. Supported: {avail_str}",
                "detail": f"Refresh rate {refresh_rate}Hz not supported.",
                "supported_refresh_rates": sorted(list(supported_freqs)),
            }

        user32 = ctypes.windll.user32
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(dev_name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            return {"status": "error", "message": "Failed to read current display settings."}

        dm.dmDisplayFrequency = refresh_rate
        dm.dmFields = DM_DISPLAYFREQUENCY

        test_res = user32.ChangeDisplaySettingsExW(dev_name, ctypes.byref(dm), None, CDS_TEST, None)
        if test_res != DISP_CHANGE_SUCCESSFUL:
            try:
                os.startfile("ms-settings:display")
            except Exception:
                pass
            msg = (
                f"Windows display driver rejected direct refresh rate change to {refresh_rate}Hz (CDS_TEST code {test_res}). "
                "Opened Windows Display Settings for manual selection."
            )
            return {
                "status": "restricted",
                "action": "navigated",
                "target_uri": "ms-settings:display",
                "test_code": test_res,
                "message": msg,
                "detail": msg,
            }

        apply_res = user32.ChangeDisplaySettingsExW(dev_name, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
        if apply_res != DISP_CHANGE_SUCCESSFUL:
            return {"status": "error", "message": f"Failed to apply refresh rate change: error code {apply_res}"}

        verify_dm = DEVMODEW()
        verify_dm.dmSize = ctypes.sizeof(DEVMODEW)
        user32.EnumDisplaySettingsW(dev_name, ENUM_CURRENT_SETTINGS, ctypes.byref(verify_dm))
        actual_freq = int(verify_dm.dmDisplayFrequency)

        if actual_freq == refresh_rate:
            msg = f"Display refresh rate successfully changed to {refresh_rate}Hz."
            return {
                "status": "ok",
                "action": "set_refresh_rate",
                "refresh_rate": actual_freq,
                "verified": True,
                "message": msg,
                "detail": msg,
            }
        else:
            return {
                "status": "failed",
                "message": f"Refresh rate verification failed: active rate is {actual_freq}Hz, expected {refresh_rate}Hz.",
            }

    def _set_orientation(self, orientation_str: str) -> Dict[str, Any]:
        """Validate and apply display orientation using Win32 ChangeDisplaySettingsExW."""
        if sys.platform != "win32":
            return {"status": "unsupported", "message": "Orientation control is only implemented on Windows."}

        orient_code = ORIENTATION_REVERSE_MAP.get(orientation_str.lower().strip())
        if orient_code is None:
            return {"status": "error", "message": f"Invalid orientation '{orientation_str}'."}

        devices = _get_active_display_devices()
        primary_dev = next((d for d in devices if d.get("is_primary")), devices[0] if devices else None)
        dev_name = primary_dev["device_name"] if primary_dev else None

        user32 = ctypes.windll.user32
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(DEVMODEW)
        if not user32.EnumDisplaySettingsW(dev_name, ENUM_CURRENT_SETTINGS, ctypes.byref(dm)):
            return {"status": "error", "message": "Failed to read current display settings."}

        # If switching between landscape and portrait, swap width and height
        current_orient = int(dm.dmDisplayOrientation)
        is_current_portrait = current_orient in (1, 3)
        is_target_portrait = orient_code in (1, 3)

        dm.dmDisplayOrientation = orient_code
        dm.dmFields = DM_DISPLAYORIENTATION
        if is_current_portrait != is_target_portrait:
            dm.dmPelsWidth, dm.dmPelsHeight = dm.dmPelsHeight, dm.dmPelsWidth
            dm.dmFields |= DM_PELSWIDTH | DM_PELSHEIGHT

        test_res = user32.ChangeDisplaySettingsExW(dev_name, ctypes.byref(dm), None, CDS_TEST, None)
        if test_res != DISP_CHANGE_SUCCESSFUL:
            try:
                os.startfile("ms-settings:display")
            except Exception:
                pass
            msg = (
                f"Windows display driver rejected direct orientation change to {orientation_str} (CDS_TEST code {test_res}). "
                "Opened Windows Display Settings for manual selection."
            )
            return {
                "status": "restricted",
                "action": "navigated",
                "target_uri": "ms-settings:display",
                "test_code": test_res,
                "message": msg,
                "detail": msg,
            }

        apply_res = user32.ChangeDisplaySettingsExW(dev_name, ctypes.byref(dm), None, CDS_UPDATEREGISTRY, None)
        if apply_res != DISP_CHANGE_SUCCESSFUL:
            return {"status": "error", "message": f"Failed to apply orientation change: error code {apply_res}"}

        verify_dm = DEVMODEW()
        verify_dm.dmSize = ctypes.sizeof(DEVMODEW)
        user32.EnumDisplaySettingsW(dev_name, ENUM_CURRENT_SETTINGS, ctypes.byref(verify_dm))
        actual_code = int(verify_dm.dmDisplayOrientation)
        actual_str = ORIENTATION_MAP.get(actual_code, "unknown")

        if actual_code == orient_code:
            msg = f"Display orientation successfully changed to {actual_str}."
            return {
                "status": "ok",
                "action": "set_orientation",
                "orientation": actual_str,
                "verified": True,
                "message": msg,
                "detail": msg,
            }
        else:
            return {
                "status": "failed",
                "message": f"Orientation verification failed: active orientation is {actual_str}, expected {orientation_str}.",
            }

    # -------------------------------------------------------------------------
    # Night Light Handler
    # -------------------------------------------------------------------------

    def _handle_night_light(self) -> Dict[str, Any]:
        """
        Handle Night Light requests honestly.
        Windows restricts direct programmatic Night Light mutations without public APIs
        (internal state is stored in an undocumented binary CloudStore registry key).
        Nova navigates to ms-settings:nightlight and informs the caller honestly.
        """
        target_uri = "ms-settings:nightlight"
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(target_uri)
            else:
                webbrowser.open(target_uri)
        except Exception as exc:
            logger.warning("Failed to open %s: %s", target_uri, exc)

        msg = (
            "Windows restricts direct programmatic control of Night Light (internal CloudStore state is protected). "
            "Opened Night Light Settings for you to toggle or adjust schedules."
        )
        return {
            "status": "restricted",
            "action": "navigated",
            "feature": "night_light",
            "target_uri": target_uri,
            "message": msg,
            "detail": msg,
        }

    # -------------------------------------------------------------------------
    # Execute Dispatcher
    # -------------------------------------------------------------------------

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action")
        if not action or not isinstance(action, str):
            # Backward-compatibility fallback for set_brightness
            if intent_data.get("intent") in ("set_brightness", "brightness"):
                action = "set_brightness"
            else:
                return {"status": "error", "message": "Missing required parameter 'action'"}

        clean_action = action.strip().lower()

        # Handle brightness aliases
        if clean_action == "set":
            clean_action = "set_brightness"
        elif clean_action == "increase":
            clean_action = "increase_brightness"
        elif clean_action == "decrease":
            clean_action = "decrease_brightness"

        try:
            if clean_action == "get_brightness":
                return self._get_brightness()

            elif clean_action == "set_brightness":
                level = intent_data.get("level")
                if level is None:
                    return {"status": "error", "message": "Missing 'level' parameter for set_brightness"}
                return self._set_brightness(int(level))

            elif clean_action in ("increase_brightness", "decrease_brightness"):
                amount = intent_data.get("amount")
                step = _parse_step_amount(amount, default=10)
                delta = -abs(step) if clean_action == "decrease_brightness" else abs(step)
                return self._adjust_brightness(delta)

            elif clean_action == "get_display_info":
                return self._get_display_info()

            elif clean_action == "get_resolution":
                info = self._get_display_info()
                if info.get("status") != "ok":
                    return info
                primary = info["primary_display"]
                msg = f"Current resolution is {primary['width']} by {primary['height']}."
                return {
                    "status": "ok",
                    "action": "get_resolution",
                    "width": primary["width"],
                    "height": primary["height"],
                    "message": msg,
                    "detail": msg,
                }

            elif clean_action == "set_resolution":
                width = intent_data.get("width")
                height = intent_data.get("height")
                if width is None or height is None:
                    return {"status": "error", "message": "set_resolution requires 'width' and 'height' parameters"}
                return self._set_resolution(int(width), int(height))

            elif clean_action == "get_refresh_rate":
                info = self._get_display_info()
                if info.get("status") != "ok":
                    return info
                primary = info["primary_display"]
                msg = f"Current refresh rate is {primary['refresh_rate']} Hz."
                return {
                    "status": "ok",
                    "action": "get_refresh_rate",
                    "refresh_rate": primary["refresh_rate"],
                    "message": msg,
                    "detail": msg,
                }

            elif clean_action == "set_refresh_rate":
                rate = intent_data.get("refresh_rate")
                if rate is None:
                    return {"status": "error", "message": "set_refresh_rate requires 'refresh_rate' parameter"}
                return self._set_refresh_rate(int(rate))

            elif clean_action == "get_orientation":
                info = self._get_display_info()
                if info.get("status") != "ok":
                    return info
                primary = info["primary_display"]
                msg = f"Current orientation is {primary['orientation']}."
                return {
                    "status": "ok",
                    "action": "get_orientation",
                    "orientation": primary["orientation"],
                    "message": msg,
                    "detail": msg,
                }

            elif clean_action == "set_orientation":
                orient = intent_data.get("orientation")
                if not orient or not isinstance(orient, str):
                    return {"status": "error", "message": "set_orientation requires 'orientation' parameter"}
                return self._set_orientation(orient)

            elif clean_action == "night_light":
                return self._handle_night_light()

            else:
                return {"status": "error", "message": f"Unknown display action '{action}'"}

        except Exception as exc:
            logger.exception("DisplaySkill execution failed: %s", exc)
            return {"status": "error", "message": f"Display control failed: {exc}"}


# Register DisplaySkill with global singleton
registry.register(DisplaySkill())
