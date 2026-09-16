"""
Power skill – control and query Windows power states, battery telemetry,
power plans/schemes, display and sleep timeouts, battery saver, and hibernation.
"""

import ctypes
from ctypes import wintypes
import logging
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional, Tuple

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.power")

# ---------------------------------------------------------------------------
# Win32 Structures & Constants
# ---------------------------------------------------------------------------

class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


# Win32 Power & Battery Constants
AC_LINE_OFFLINE = 0
AC_LINE_ONLINE = 1
AC_LINE_UNKNOWN = 255

BATTERY_FLAG_HIGH = 1
BATTERY_FLAG_LOW = 2
BATTERY_FLAG_CRITICAL = 4
BATTERY_FLAG_CHARGING = 8
BATTERY_FLAG_NO_BATTERY = 128
BATTERY_FLAG_UNKNOWN = 255

BATTERY_PERCENTAGE_UNKNOWN = 255


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    def __str__(self) -> str:
        d4_1 = "".join(f"{self.Data4[i]:02x}" for i in range(2))
        d4_2 = "".join(f"{self.Data4[i]:02x}" for i in range(2, 8))
        return f"{self.Data1:08x}-{self.Data2:04x}-{self.Data3:04x}-{d4_1}-{d4_2}"


ACCESS_SCHEME = 16
ERROR_ACCESS_DENIED = 5


def _is_access_denied(text: str) -> bool:
    """Check whether a return message or code denotes access denied / requires elevation."""
    if not text:
        return False
    lower = text.lower()
    return any(
        k in lower
        for k in (
            "access is denied",
            "permissions required",
            "requires elevation",
            "administrator",
            "privilege",
            "0x80070005",
        )
    )


# ---------------------------------------------------------------------------
# Native Win32 Helper Functions
# ---------------------------------------------------------------------------

def _get_system_power_status() -> Optional[SYSTEM_POWER_STATUS]:
    """Retrieve raw SYSTEM_POWER_STATUS from kernel32."""
    if sys.platform != "win32":
        return None
    try:
        sps = SYSTEM_POWER_STATUS()
        if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            return sps
    except Exception as exc:
        logger.debug("GetSystemPowerStatus failed: %s", exc)
    return None


def _get_active_power_scheme() -> Tuple[Optional[str], Optional[str]]:
    """Retrieve current active power scheme GUID string and friendly name."""
    if sys.platform != "win32":
        return None, None
    try:
        p_guid = ctypes.POINTER(GUID)()
        ret = ctypes.windll.powrprof.PowerGetActiveScheme(None, ctypes.byref(p_guid))
        if ret == 0 and p_guid:
            guid_str = str(p_guid.contents)
            buf_size = wintypes.DWORD(256)
            buf = (wintypes.WCHAR * 256)()
            name_ret = ctypes.windll.powrprof.PowerReadFriendlyName(
                None,
                p_guid,
                None,
                None,
                buf,
                ctypes.byref(buf_size),
            )
            friendly_name = buf.value if name_ret == 0 else ""
            ctypes.windll.kernel32.LocalFree(p_guid)
            return guid_str, friendly_name
    except Exception as exc:
        logger.debug("PowerGetActiveScheme native call failed: %s", exc)

    # CLI fallback
    try:
        res = subprocess.run(
            ["powercfg", "/getactivescheme"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0:
            m = re.search(r"GUID:\s*([a-fA-F0-9\-]+)\s*\((.+?)\)", res.stdout)
            if m:
                return m.group(1).strip(), m.group(2).strip()
    except Exception as exc:
        logger.debug("powercfg /getactivescheme fallback failed: %s", exc)

    return None, None


def _enumerate_power_schemes() -> List[Dict[str, str]]:
    """Enumerate all available power schemes on the system dynamically."""
    if sys.platform != "win32":
        return []
    schemes: List[Dict[str, str]] = []
    try:
        index = 0
        while True:
            scheme_guid = GUID()
            buf_size = wintypes.DWORD(ctypes.sizeof(GUID))
            status = ctypes.windll.powrprof.PowerEnumerate(
                None,
                None,
                None,
                ACCESS_SCHEME,
                index,
                ctypes.byref(scheme_guid),
                ctypes.byref(buf_size),
            )
            if status != 0:
                break
            guid_str = str(scheme_guid)
            buf_size_name = wintypes.DWORD(256)
            buf_name = (wintypes.WCHAR * 256)()
            ctypes.windll.powrprof.PowerReadFriendlyName(
                None,
                ctypes.byref(scheme_guid),
                None,
                None,
                buf_name,
                ctypes.byref(buf_size_name),
            )
            schemes.append({
                "guid": guid_str.lower(),
                "name": buf_name.value.strip() or "Unnamed Scheme",
            })
            index += 1
        if schemes:
            return schemes
    except Exception as exc:
        logger.debug("PowerEnumerate failed, falling back to CLI: %s", exc)

    # CLI Fallback
    try:
        res = subprocess.run(
            ["powercfg", "/list"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                m = re.search(r"GUID:\s*([a-fA-F0-9\-]+)\s*\((.+?)\)", line)
                if m:
                    schemes.append({
                        "guid": m.group(1).strip().lower(),
                        "name": m.group(2).strip(),
                    })
    except Exception as exc:
        logger.debug("powercfg /list failed: %s", exc)

    return schemes


def _resolve_scheme_by_name(query: str, available_schemes: List[Dict[str, str]]) -> Tuple[Optional[str], Optional[str]]:
    """
    Resolve user-requested scheme query against available schemes dynamically.
    Returns: (resolved_guid, resolved_friendly_name) or (None, None).
    """
    clean = query.strip().lower()
    if not clean:
        return None, None

    # Common semantic aliases
    alias_map = {
        "balanced": "balanced",
        "balance": "balanced",
        "high performance": "performance",
        "high_performance": "performance",
        "max performance": "performance",
        "performance": "performance",
        "power saver": "saver",
        "powersaver": "saver",
        "power_saver": "saver",
        "battery saver": "saver",
        "silent": "silent",
        "quiet": "silent",
        "turbo": "turbo",
    }
    target_keyword = alias_map.get(clean, clean)

    # 1. Exact match on friendly name
    for s in available_schemes:
        if s["name"].lower() == clean:
            return s["guid"], s["name"]

    # 2. Substring match
    for s in available_schemes:
        if clean in s["name"].lower():
            return s["guid"], s["name"]

    # 3. Target keyword match
    for s in available_schemes:
        if target_keyword in s["name"].lower():
            return s["guid"], s["name"]

    return None, None


def _query_timeouts_cli() -> Dict[str, Optional[int]]:
    """Query display and sleep timeouts in minutes via powercfg /query."""
    results: Dict[str, Optional[int]] = {
        "display_timeout_ac_min": None,
        "display_timeout_dc_min": None,
        "sleep_timeout_ac_min": None,
        "sleep_timeout_dc_min": None,
    }
    if sys.platform != "win32":
        return results

    try:
        r_disp = subprocess.run(
            ["powercfg", "/query", "SCHEME_CURRENT", "SUB_VIDEO", "VIDEOIDLE"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if r_disp.returncode == 0:
            for line in r_disp.stdout.splitlines():
                if "Current AC Power Setting Index:" in line:
                    val_hex = line.split(":")[-1].strip()
                    results["display_timeout_ac_min"] = int(val_hex, 16) // 60
                elif "Current DC Power Setting Index:" in line:
                    val_hex = line.split(":")[-1].strip()
                    results["display_timeout_dc_min"] = int(val_hex, 16) // 60

        r_sleep = subprocess.run(
            ["powercfg", "/query", "SCHEME_CURRENT", "SUB_SLEEP", "STANDBYIDLE"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if r_sleep.returncode == 0:
            for line in r_sleep.stdout.splitlines():
                if "Current AC Power Setting Index:" in line:
                    val_hex = line.split(":")[-1].strip()
                    results["sleep_timeout_ac_min"] = int(val_hex, 16) // 60
                elif "Current DC Power Setting Index:" in line:
                    val_hex = line.split(":")[-1].strip()
                    results["sleep_timeout_dc_min"] = int(val_hex, 16) // 60
    except Exception as exc:
        logger.debug("Failed to query timeouts via powercfg: %s", exc)

    return results


# ---------------------------------------------------------------------------
# PowerSkill Implementation
# ---------------------------------------------------------------------------

class PowerSkill(BaseSkill):
    """
    Canonical Windows Power, Battery & Energy Management Skill.
    Controls and queries battery telemetry, power plans/modes, idle timeouts,
    battery saver status, and system hibernation.
    """
    intent = "power"
    description = (
        "Control and inspect Windows power states: battery level, charging status, "
        "active power scheme/plan, display and sleep timeouts, battery saver, and hibernation."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_battery_status",
                    "get_power_scheme",
                    "set_power_scheme",
                    "get_timeouts",
                    "set_timeout",
                    "get_battery_saver",
                    "hibernate",
                ],
                "description": "Power action to perform.",
            },
            "scheme": {
                "type": "string",
                "description": "Target power scheme name (e.g. 'balanced', 'high performance', 'power saver', 'turbo'). Resolved dynamically.",
            },
            "target": {
                "type": "string",
                "enum": ["display", "sleep"],
                "description": "Timeout target when setting timeouts ('display' or 'sleep').",
            },
            "minutes": {
                "type": "integer",
                "minimum": 0,
                "maximum": 1440,
                "description": "Timeout duration in minutes (0 means never turn off / sleep).",
            },
            "source": {
                "type": "string",
                "enum": ["ac", "dc", "both"],
                "description": "Power source for timeout ('ac' for plugged in, 'dc' for on battery, 'both' for both).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("power", "battery", "power_control", "hibernate")

    # ------------------------------------------------------------------
    # Entry Point
    # ------------------------------------------------------------------

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action", "").strip().lower()
        valid_actions = self.parameters_schema["properties"]["action"]["enum"]
        if action not in valid_actions:
            return {
                "status": "error",
                "message": f"Unknown power action: {action!r}. Valid: {', '.join(valid_actions)}.",
            }

        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Windows power management is only supported on Windows.",
            }

        if action == "get_battery_status":
            return self._do_get_battery_status()
        elif action == "get_power_scheme":
            return self._do_get_power_scheme()
        elif action == "set_power_scheme":
            return self._do_set_power_scheme(intent_data)
        elif action == "get_timeouts":
            return self._do_get_timeouts()
        elif action == "set_timeout":
            return self._do_set_timeout(intent_data)
        elif action == "get_battery_saver":
            return self._do_get_battery_saver()
        elif action == "hibernate":
            return self._do_hibernate()

        return {"status": "error", "message": f"Unhandled power action: {action}"}

    # ------------------------------------------------------------------
    # Action Implementations
    # ------------------------------------------------------------------

    def _do_get_battery_status(self) -> Dict[str, Any]:
        """Query battery percentage, AC line state, charging status, and lifetime."""
        sps = _get_system_power_status()
        if not sps:
            return {
                "status": "error",
                "message": "Failed to query Windows system power status.",
            }

        has_battery = not bool(sps.BatteryFlag & 128) and (sps.BatteryLifePercent != 255)
        ac_power = "online" if sps.ACLineStatus == 1 else "offline" if sps.ACLineStatus == 0 else "unknown"
        is_charging = bool(sps.BatteryFlag & 8)
        battery_pct = int(sps.BatteryLifePercent) if sps.BatteryLifePercent <= 100 else None
        lifetime_sec = int(sps.BatteryLifeTime) if sps.BatteryLifeTime != 0xFFFFFFFF else None
        battery_saver_active = bool(sps.SystemStatusFlag == 1)

        if not has_battery:
            detail = f"AC power is {ac_power}. No battery detected (desktop system)."
        else:
            state_str = "charging" if is_charging else "discharging" if ac_power == "offline" else "plugged in"
            pct_str = f"{battery_pct}%" if battery_pct is not None else "unknown %"
            detail = f"Battery at {pct_str} ({state_str}). AC power is {ac_power}."

        return {
            "status": "ok",
            "has_battery": has_battery,
            "ac_power": ac_power,
            "is_charging": is_charging,
            "battery_percentage": battery_pct,
            "battery_lifetime_seconds": lifetime_sec,
            "battery_saver_active": battery_saver_active,
            "raw_battery_flag": int(sps.BatteryFlag),
            "detail": detail,
        }

    def _do_get_power_scheme(self) -> Dict[str, Any]:
        """Query active Windows power scheme and enumerate available schemes."""
        active_guid, active_name = _get_active_power_scheme()
        available = _enumerate_power_schemes()

        if not active_guid:
            return {
                "status": "error",
                "message": "Failed to query active Windows power scheme.",
            }

        return {
            "status": "ok",
            "active_guid": active_guid,
            "active_scheme": active_name or "Unknown Scheme",
            "available_schemes": [s["name"] for s in available],
            "detail": f"Active power scheme is '{active_name}' ({active_guid}).",
        }

    def _do_set_power_scheme(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Switch active power scheme dynamically with read-back verification."""
        requested_scheme = intent_data.get("scheme", "").strip()
        if not requested_scheme:
            return {
                "status": "error",
                "message": "Missing required 'scheme' parameter for set_power_scheme.",
            }

        available = _enumerate_power_schemes()
        resolved_guid, resolved_name = _resolve_scheme_by_name(requested_scheme, available)

        if not resolved_guid or not resolved_name:
            avail_names = ", ".join(f"'{s['name']}'" for s in available) if available else "None"
            return {
                "status": "error",
                "message": f"No power scheme matching '{requested_scheme}'. Available schemes: {avail_names}.",
            }

        curr_guid, curr_name = _get_active_power_scheme()
        if curr_guid and curr_guid.lower() == resolved_guid.lower():
            return {
                "status": "ok",
                "active_scheme": resolved_name,
                "active_guid": resolved_guid,
                "detail": f"Power scheme is already set to '{resolved_name}'.",
            }

        # Try native Win32 PowerSetActiveScheme first
        access_denied = False
        native_success = False
        try:
            g = GUID()
            hr = ctypes.windll.ole32.CLSIDFromString(wintypes.LPCWSTR(f"{{{resolved_guid}}}"), ctypes.byref(g))
            if hr == 0:
                ret = ctypes.windll.powrprof.PowerSetActiveScheme(None, ctypes.byref(g))
                if ret == 0:
                    native_success = True
                elif ret == ERROR_ACCESS_DENIED:
                    access_denied = True
        except Exception as exc:
            logger.debug("Native PowerSetActiveScheme threw: %s", exc)

        # Fallback to powercfg /setactive <resolved_guid>
        if not native_success and not access_denied:
            try:
                res = subprocess.run(
                    ["powercfg", "/setactive", resolved_guid],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=5,
                )
                if res.returncode != 0:
                    if _is_access_denied(res.stderr or res.stdout):
                        access_denied = True
            except Exception as exc:
                logger.debug("powercfg /setactive execution error: %s", exc)

        if access_denied:
            return {
                "status": "restricted",
                "message": "Changing Windows power schemes requires administrator privileges.",
                "target_scheme": resolved_name,
                "fallback": "ms-settings:powersleep",
                "detail": "Action restricted. Open Settings to change power mode.",
            }

        # Read-back verification
        verified_guid, verified_name = _get_active_power_scheme()
        if verified_guid and verified_guid.lower() == resolved_guid.lower():
            return {
                "status": "ok",
                "previous_scheme": curr_name,
                "active_scheme": verified_name,
                "active_guid": verified_guid,
                "detail": f"Switched power scheme to '{verified_name}'.",
            }

        return {
            "status": "error",
            "message": f"Failed to switch power scheme to '{resolved_name}'. Read-back returned '{verified_name}'.",
        }

    def _do_get_timeouts(self) -> Dict[str, Any]:
        """Query current display and sleep idle timeouts."""
        timeouts = _query_timeouts_cli()
        return {
            "status": "ok",
            "display_timeout_ac_min": timeouts["display_timeout_ac_min"],
            "display_timeout_dc_min": timeouts["display_timeout_dc_min"],
            "sleep_timeout_ac_min": timeouts["sleep_timeout_ac_min"],
            "sleep_timeout_dc_min": timeouts["sleep_timeout_dc_min"],
            "detail": (
                f"Display timeout: {timeouts['display_timeout_ac_min']}m (AC), {timeouts['display_timeout_dc_min']}m (Battery). "
                f"Sleep timeout: {timeouts['sleep_timeout_ac_min']}m (AC), {timeouts['sleep_timeout_dc_min']}m (Battery)."
            ),
        }

    def _do_set_timeout(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Set display or sleep timeout in minutes for AC, DC, or both."""
        target = intent_data.get("target", "").strip().lower()
        if target not in ("display", "sleep"):
            return {
                "status": "error",
                "message": f"Invalid timeout target: {target!r}. Must be 'display' or 'sleep'.",
            }

        minutes = intent_data.get("minutes")
        if minutes is None or not isinstance(minutes, int) or minutes < 0 or minutes > 1440:
            return {
                "status": "error",
                "message": f"Invalid minutes: {minutes!r}. Must be an integer between 0 and 1440.",
            }

        source = intent_data.get("source", "both").strip().lower()
        if source not in ("ac", "dc", "both"):
            return {
                "status": "error",
                "message": f"Invalid source: {source!r}. Must be 'ac', 'dc', or 'both'.",
            }

        # Determine CLI commands to run
        commands: List[List[str]] = []
        if target == "display":
            if source in ("ac", "both"):
                commands.append(["powercfg", "/change", "monitor-timeout-ac", str(minutes)])
            if source in ("dc", "both"):
                commands.append(["powercfg", "/change", "monitor-timeout-dc", str(minutes)])
        elif target == "sleep":
            if source in ("ac", "both"):
                commands.append(["powercfg", "/change", "standby-timeout-ac", str(minutes)])
            if source in ("dc", "both"):
                commands.append(["powercfg", "/change", "standby-timeout-dc", str(minutes)])

        access_denied = False
        for cmd in commands:
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=5)
                if res.returncode != 0:
                    if _is_access_denied(res.stderr or res.stdout):
                        access_denied = True
                        break
                    else:
                        return {
                            "status": "error",
                            "message": f"Failed to set {target} timeout: {res.stderr.strip() or res.stdout.strip()}",
                        }
            except Exception as exc:
                return {"status": "error", "message": f"powercfg /change failed: {exc}"}

        if access_denied:
            return {
                "status": "restricted",
                "message": "Modifying Windows idle timeouts requires administrator privileges.",
                "target": target,
                "minutes": minutes,
                "fallback": "ms-settings:powersleep",
                "detail": "Action restricted. Open Settings to modify sleep/display timeouts.",
            }

        # Read-back verification
        verified = _query_timeouts_cli()
        failed_checks = []
        if target == "display":
            if source in ("ac", "both") and verified["display_timeout_ac_min"] != minutes:
                failed_checks.append(f"AC expected {minutes}m but got {verified['display_timeout_ac_min']}m")
            if source in ("dc", "both") and verified["display_timeout_dc_min"] != minutes:
                failed_checks.append(f"DC expected {minutes}m but got {verified['display_timeout_dc_min']}m")
        elif target == "sleep":
            if source in ("ac", "both") and verified["sleep_timeout_ac_min"] != minutes:
                failed_checks.append(f"AC expected {minutes}m but got {verified['sleep_timeout_ac_min']}m")
            if source in ("dc", "both") and verified["sleep_timeout_dc_min"] != minutes:
                failed_checks.append(f"DC expected {minutes}m but got {verified['sleep_timeout_dc_min']}m")

        if failed_checks:
            return {
                "status": "error",
                "message": f"Timeout read-back mismatch: {', '.join(failed_checks)}.",
            }

        target_desc = "display turn-off" if target == "display" else "PC sleep"
        dur_desc = "never" if minutes == 0 else f"{minutes} minutes"
        return {
            "status": "ok",
            "target": target,
            "minutes": minutes,
            "source": source,
            "detail": f"Set {target_desc} timeout to {dur_desc} ({source}).",
        }

    def _do_get_battery_saver(self) -> Dict[str, Any]:
        """Query real battery saver / energy saver status."""
        sps = _get_system_power_status()
        if not sps:
            return {
                "status": "error",
                "message": "Failed to read battery saver status.",
            }

        active = bool(sps.SystemStatusFlag == 1)
        return {
            "status": "ok",
            "battery_saver_active": active,
            "detail": f"Battery saver is currently {'ON' if active else 'OFF'}.",
        }

    def _is_hibernation_enabled(self) -> bool:
        """Check if hibernation is supported and enabled on this system."""
        try:
            r_cap = subprocess.run(
                ["powercfg", "/availablesleepstates"],
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            out_lower = r_cap.stdout.lower()
            return "hibernate" in out_lower and "hibernation has not been enabled" not in out_lower
        except Exception as exc:
            logger.debug("Failed to check hibernation capability: %s", exc)
            return False

    def _do_hibernate(self) -> Dict[str, Any]:
        """Put the computer into hibernation after capability check."""
        if not self._is_hibernation_enabled():
            return {
                "status": "unsupported",
                "message": "Hibernation is not supported or not enabled on this system.",
            }

        try:
            # shutdown.exe /h
            subprocess.run(
                [r"C:\Windows\System32\shutdown.exe", "/h"],
                check=True,
                timeout=5,
            )
            logger.info("Hibernation command issued")
            return {
                "status": "ok",
                "detail": "Entering hibernation.",
            }
        except Exception as exc:
            logger.exception("Failed to execute hibernation: %s", exc)
            return {
                "status": "error",
                "message": f"Failed to execute hibernation: {exc}",
            }


registry.register(PowerSkill())
