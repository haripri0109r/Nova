"""
Wi-Fi skill – enable/disable/connect/status (Windows netsh, read-back verified).

Phase 5.8-D.  Nova is "Siri for Windows" – this skill controls the real Wi-Fi
radio and network stack, NOT Windows Settings navigation.

Actions
-------
enable    – Enable the Wi-Fi radio on the active WLAN interface.
disable   – Disable the Wi-Fi radio on the active WLAN interface.
status    – Report current interface state and connected SSID.
connect   – Connect to an existing saved Windows Wi-Fi profile.
           Does NOT create or modify profiles.

Design rules
------------
* NO shell=True.
* All subprocess calls use explicit list args.
* Every mutating action is followed by a read-back of actual state.
* Access-denied → status="restricted" (not "error").
* Missing interface → status="unsupported".
* connect to unknown profile → status="restricted" with Settings fallback.
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
import time
from typing import Any, Dict, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.wifi")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_SSID_RE = re.compile(r"^\s*SSID\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_STATE_RE = re.compile(r"^\s*State\s*:\s*(\S+)", re.MULTILINE | re.IGNORECASE)
_BSSID_RE = re.compile(r"^\s*BSSID\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE)
_INTERFACE_NAME_RE = re.compile(
    r"^\s*Name\s*:\s*(.+)$", re.MULTILINE | re.IGNORECASE
)


def _run(args: list[str], timeout: int = 12) -> subprocess.CompletedProcess:
    """Run a subprocess without shell=True."""
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _find_wlan_interface() -> Optional[str]:
    """
    Discover the primary Wi-Fi interface name via `netsh wlan show interface`.
    Returns the interface name string, or None if WLAN service unavailable.
    """
    if sys.platform != "win32":
        return None
    try:
        res = _run(["netsh", "wlan", "show", "interface"])
        if res.returncode != 0:
            return None
        m = _INTERFACE_NAME_RE.search(res.stdout)
        if m:
            return m.group(1).strip()
    except Exception as exc:  # noqa: BLE001
        logger.debug("WLAN interface discovery failed: %s", exc)
    return None


def _get_wlan_state() -> Dict[str, Any]:
    """
    Return real-time Wi-Fi state: interface, state, ssid.
    Uses `netsh wlan show interface`.
    """
    if sys.platform != "win32":
        return {"available": False, "reason": "not_windows"}
    try:
        res = _run(["netsh", "wlan", "show", "interface"])
        if res.returncode != 0:
            stdout_lower = res.stdout.lower()
            if "hosted network" in stdout_lower or "autoconfig" in stdout_lower:
                return {"available": False, "reason": "wlan_service_unavailable"}
            return {"available": False, "reason": "no_wlan_interface"}

        iface_m = _INTERFACE_NAME_RE.search(res.stdout)
        state_m = _STATE_RE.search(res.stdout)
        ssid_m = _SSID_RE.search(res.stdout)

        return {
            "available": True,
            "interface": iface_m.group(1).strip() if iface_m else "Wi-Fi",
            "state": state_m.group(1).strip().lower() if state_m else "unknown",
            "ssid": ssid_m.group(1).strip() if ssid_m else None,
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("WLAN state query failed: %s", exc)
        return {"available": False, "reason": str(exc)}


def _get_netsh_interface_state(interface_name: str) -> Optional[str]:
    """
    Return the admin/connection state of a named network interface
    via `netsh interface show interface <name>`.
    Returns 'enabled'/'disabled' or None on error.
    """
    try:
        res = _run(["netsh", "interface", "show", "interface", interface_name])
        if res.returncode != 0:
            return None
        stdout_lower = res.stdout.lower()
        if "enabled" in stdout_lower:
            return "enabled"
        if "disabled" in stdout_lower:
            return "disabled"
        return None
    except Exception:  # noqa: BLE001
        return None


def _is_access_denied(text: str) -> bool:
    return any(
        k in text.lower()
        for k in (
            "access is denied",
            "requires elevation",
            "administrator",
            "privilege",
            "0x80070005",
        )
    )


def _sanitize_ssid(ssid: str) -> str:
    """
    Sanitize SSID for use as a CLI argument.
    Only printable ASCII except shell metacharacters allowed.
    """
    allowed = re.compile(r"^[\w\s\-_\.\(\)\[\]@#!]{1,32}$")
    if not allowed.match(ssid):
        raise ValueError(f"SSID contains unsupported characters: {ssid!r}")
    return ssid


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------


class WifiSkill(BaseSkill):
    intent = "wifi"
    description = (
        "Enable, disable, or connect to Wi-Fi networks on Windows. "
        "Connect only works for existing saved profiles – it does not create profiles."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["enable", "disable", "status", "connect"],
                "description": "Action to perform on Wi-Fi.",
            },
            "ssid": {
                "type": "string",
                "description": "SSID/profile name to connect to (required for connect).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("wifi", "wifi_control")

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action", "").strip().lower()
        if action not in ("enable", "disable", "status", "connect"):
            return {
                "status": "error",
                "message": f"Unknown wifi action: {action!r}. "
                           "Valid: enable, disable, status, connect.",
            }

        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Wi-Fi control is only supported on Windows.",
            }

        if action == "status":
            return self._do_status()
        if action == "enable":
            return self._do_toggle("enable")
        if action == "disable":
            return self._do_toggle("disable")
        if action == "connect":
            ssid = intent_data.get("ssid", "").strip()
            if not ssid:
                return {
                    "status": "error",
                    "message": "connect requires an 'ssid' parameter.",
                }
            return self._do_connect(ssid)

    # ------------------------------------------------------------------
    # status
    # ------------------------------------------------------------------

    def _do_status(self) -> Dict[str, Any]:
        state = _get_wlan_state()
        if not state.get("available"):
            reason = state.get("reason", "unknown")
            return {
                "status": "unsupported",
                "message": f"Wi-Fi hardware/service not available ({reason}).",
            }
        wifi_state = state.get("state", "unknown")
        ssid = state.get("ssid")
        connected = wifi_state == "connected"
        return {
            "status": "ok",
            "wifi_state": wifi_state,
            "connected": connected,
            "ssid": ssid,
            "interface": state.get("interface", "Wi-Fi"),
            "detail": (
                f"Wi-Fi is {wifi_state}"
                + (f", connected to {ssid!r}" if ssid else "")
            ),
        }

    # ------------------------------------------------------------------
    # enable / disable
    # ------------------------------------------------------------------

    def _do_toggle(self, action: str) -> Dict[str, Any]:
        """Enable or disable the Wi-Fi interface, then read back the actual state."""
        interface_name = _find_wlan_interface()
        if not interface_name:
            return {
                "status": "unsupported",
                "message": "No Wi-Fi (WLAN) interface detected on this device.",
            }

        try:
            res = _run(
                ["netsh", "interface", "set", "interface", interface_name, action]
            )
        except FileNotFoundError:
            return {
                "status": "unsupported",
                "message": "netsh not found on this system.",
            }
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "Wi-Fi toggle timed out."}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"Wi-Fi toggle failed: {exc}"}

        # Check for access-denied in stdout/stderr
        output = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0 or _is_access_denied(output):
            if _is_access_denied(output):
                return {
                    "status": "restricted",
                    "message": (
                        f"Cannot {action} Wi-Fi: Administrator permissions required. "
                        "Run Nova as Administrator to control Wi-Fi."
                    ),
                    "settings_fallback": "ms-settings:network-wifi",
                }
            if "does not exist" in output.lower() or "not configured" in output.lower():
                return {
                    "status": "unsupported",
                    "message": f"Wi-Fi interface '{interface_name}' not found.",
                }
            return {
                "status": "error",
                "message": f"Failed to {action} Wi-Fi: {output.strip()[:200]}",
            }

        # Read back actual state after a brief settling delay
        time.sleep(0.5)
        actual_state = _get_netsh_interface_state(interface_name)

        expected_state = "enabled" if action == "enable" else "disabled"
        if actual_state and actual_state != expected_state:
            logger.warning(
                "Wi-Fi toggle read-back mismatch: expected=%s actual=%s",
                expected_state,
                actual_state,
            )
            return {
                "status": "error",
                "message": (
                    f"Wi-Fi {action} command succeeded but interface state is "
                    f"still '{actual_state}'. State may need more time to settle."
                ),
            }

        logger.info("Wi-Fi (%s) %sd (verified)", interface_name, action)
        return {
            "status": "ok",
            "action": action,
            "interface": interface_name,
            "verified_state": actual_state or "unknown",
            "detail": f"Wi-Fi {action}d (read-back: {actual_state or 'unknown'})",
        }

    # ------------------------------------------------------------------
    # connect
    # ------------------------------------------------------------------

    def _do_connect(self, ssid: str) -> Dict[str, Any]:
        """
        Connect to an existing saved Windows Wi-Fi profile.

        Safety contract:
        - Sanitizes SSID before passing to netsh.
        - Does NOT create or modify profiles.
        - Does NOT claim success unless read-back confirms connection.
        - Returns status='restricted' if profile does not exist.
        """
        try:
            clean_ssid = _sanitize_ssid(ssid)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        # First: verify the profile exists locally
        try:
            profile_check = _run(
                ["netsh", "wlan", "show", "profile", f"name={clean_ssid}"]
            )
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"Profile lookup failed: {exc}"}

        if profile_check.returncode != 0:
            output_lower = (profile_check.stdout + profile_check.stderr).lower()
            if "not found" in output_lower or "does not exist" in output_lower or "profile" in output_lower:
                return {
                    "status": "restricted",
                    "message": (
                        f"Wi-Fi profile '{ssid}' not found on this device. "
                        "Only existing saved profiles can be connected to. "
                        "To add a new network, use Wi-Fi Settings."
                    ),
                    "settings_fallback": "ms-settings:network-wifi",
                }
            if _is_access_denied(profile_check.stdout + profile_check.stderr):
                return {
                    "status": "restricted",
                    "message": "Cannot read Wi-Fi profiles: Administrator permissions required.",
                    "settings_fallback": "ms-settings:network-wifi",
                }

        # Attempt connection
        try:
            res = _run(["netsh", "wlan", "connect", f"name={clean_ssid}"])
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "Wi-Fi connect timed out."}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"Wi-Fi connect failed: {exc}"}

        output = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0 or _is_access_denied(output):
            if _is_access_denied(output):
                return {
                    "status": "restricted",
                    "message": "Cannot connect: Administrator permissions required.",
                    "settings_fallback": "ms-settings:network-wifi",
                }
            return {
                "status": "error",
                "message": f"netsh wlan connect failed: {output.strip()[:200]}",
            }

        # Read-back: wait for connection and verify actual SSID
        connected_ssid: Optional[str] = None
        for attempt in range(8):
            time.sleep(1.5)
            state = _get_wlan_state()
            if state.get("connected") and state.get("ssid"):
                connected_ssid = state["ssid"]
                break

        if not connected_ssid:
            return {
                "status": "error",
                "message": (
                    f"netsh wlan connect returned success for profile '{ssid}', "
                    "but the interface did not report a connected SSID within 12 seconds. "
                    "The connection may still be in progress."
                ),
            }

        if connected_ssid.strip().lower() != clean_ssid.strip().lower():
            logger.warning(
                "Wi-Fi connect read-back mismatch: requested=%r actual=%r",
                ssid,
                connected_ssid,
            )
            return {
                "status": "error",
                "message": (
                    f"Connected, but to '{connected_ssid}' instead of '{ssid}'. "
                    "Windows may have switched to a higher-priority saved profile."
                ),
                "connected_ssid": connected_ssid,
            }

        logger.info("Wi-Fi connected and verified: SSID=%r", connected_ssid)
        return {
            "status": "ok",
            "action": "connect",
            "ssid": connected_ssid,
            "detail": f"Connected to Wi-Fi network '{connected_ssid}' (read-back verified)",
        }


registry.register(WifiSkill())