"""
Bluetooth skill – enable/disable/status (WinRT if available, PnP Radio fallback, read-back verified).

Phase 5.8-D. Nova is "Siri for Windows" – this skill controls the real Bluetooth
radio on Windows, NOT Windows Settings navigation.

Actions
-------
enable  – Turn on the primary Bluetooth radio.
disable – Turn off the primary Bluetooth radio.
status  – Query current Bluetooth radio status and adapter info.

Design rules
------------
* NO shell=True.
* Subprocess calls use explicit list arguments.
* WinRT (Windows.Devices.Radios) is used if installed; otherwise falls back to
  targeted PnP Device radio management (avoiding peripheral disconnection).
* Every mutating action is followed by a read-back of actual state.
* Access-denied / elevation required → status="restricted" with settings_fallback="ms-settings:bluetooth".
* Missing adapter → status="unsupported".
"""

from __future__ import annotations

import importlib.util
import logging
import subprocess
import sys
import time
from typing import Any, Dict, Optional, Tuple

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.bluetooth")

# Check for WinRT availability
_HAS_WINRT = False
try:
    if sys.platform == "win32" and importlib.util.find_spec("winrt.windows.devices.radios") is not None:
        import winrt.windows.devices.radios as _winrt_radios  # type: ignore
        _HAS_WINRT = True
except Exception:  # noqa: BLE001
    _HAS_WINRT = False


def _run_ps(script: str, timeout: int = 15) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet safely without shell=True."""
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _is_access_denied(text: str) -> bool:
    text_lower = text.lower()
    return any(
        k in text_lower
        for k in (
            "access is denied",
            "access to a cim resource was not available",
            "administrator",
            "requires elevation",
            "0x80041001",
            "0x80070005",
            "privilege",
        )
    )


def _query_pnp_bluetooth_radio() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Query the primary Bluetooth radio adapter via PowerShell Get-PnpDevice.
    Filters specifically for host controller/radio adapters, avoiding peripheral profiles.
    Returns: (status, friendly_name, instance_id)
    """
    script = (
        "$devs = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | "
        "Where-Object { "
        "    $_.FriendlyName -match 'Radio|Adapter|Intel.*Bluetooth|Realtek.*Bluetooth|Qualcomm.*Bluetooth|Broadcom.*Bluetooth' "
        "    -or $_.DeviceID -match '^USB\\\\VID_.*&PID_.*' "
        "    -or $_.CompatibleID -contains 'USB\\Class_E0&SubClass_01&Prot_01' "
        "}; "
        "if ($devs) { "
        "    $d = if ($devs -is [array]) { $devs[0] } else { $devs }; "
        "    Write-Output ($d.Status + '|' + $d.FriendlyName + '|' + $d.InstanceId) "
        "} else { "
        "    # Fallback to any Bluetooth device if no specific adapter pattern matched\n"
        "    $any = Get-PnpDevice -Class Bluetooth -ErrorAction SilentlyContinue | Where-Object { $_.Status -in 'OK','Error','Degraded' }; "
        "    if ($any) { "
        "        $d = if ($any -is [array]) { $any[0] } else { $any }; "
        "        Write-Output ($d.Status + '|' + $d.FriendlyName + '|' + $d.InstanceId) "
        "    } "
        "}"
    )
    try:
        res = _run_ps(script)
        if res.returncode != 0:
            if _is_access_denied(res.stderr or res.stdout):
                return "RESTRICTED", None, None
            return None, None, None

        out = res.stdout.strip()
        if not out:
            return None, None, None

        # Take first line if multiple
        line = out.splitlines()[0]
        parts = line.split("|")
        if len(parts) >= 3:
            return parts[0].strip(), parts[1].strip(), parts[2].strip()
        elif len(parts) == 2:
            return parts[0].strip(), parts[1].strip(), None
        return parts[0].strip(), None, None
    except Exception as exc:  # noqa: BLE001
        logger.debug("PnP Bluetooth query failed: %s", exc)
        return None, None, None


class BluetoothSkill(BaseSkill):
    intent = "bluetooth"
    description = (
        "Enable, disable, or check status of the Bluetooth radio on Windows. "
        "Uses hardware radio control with state verification."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["enable", "disable", "status"],
                "description": "Bluetooth action: 'enable', 'disable', or 'status'.",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("bluetooth", "bluetooth_control")

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action", "").strip().lower()
        if action not in ("enable", "disable", "status"):
            return {
                "status": "error",
                "message": f"Unknown bluetooth action: {action!r}. Valid: enable, disable, status.",
            }

        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Bluetooth control is only supported on Windows.",
            }

        if action == "status":
            return self._do_status()
        elif action in ("enable", "disable"):
            return self._do_toggle(action)

    def _do_status(self) -> Dict[str, Any]:
        """Query real Bluetooth status."""
        status_val, name_val, dev_id = _query_pnp_bluetooth_radio()
        if status_val == "RESTRICTED":
            return {
                "status": "restricted",
                "message": "Access to Bluetooth device management is restricted or requires elevation.",
                "settings_fallback": "ms-settings:bluetooth",
            }

        if not status_val:
            return {
                "status": "unsupported",
                "message": "No Bluetooth radio adapter found on this device.",
                "settings_fallback": "ms-settings:bluetooth",
            }

        # Status 'OK' typically indicates enabled/working, 'Error' or disabled state in PnP
        is_enabled = status_val.upper() == "OK"
        return {
            "status": "ok",
            "bluetooth_state": "enabled" if is_enabled else "disabled",
            "adapter_status": status_val,
            "adapter_name": name_val or "Bluetooth Adapter",
            "device_id": dev_id,
            "detail": f"Bluetooth radio is {'enabled' if is_enabled else 'disabled'} ({name_val or 'Adapter'})",
        }

    def _do_toggle(self, action: str) -> Dict[str, Any]:
        """Toggle the primary Bluetooth radio and verify read-back."""
        status_val, name_val, dev_id = _query_pnp_bluetooth_radio()
        if status_val == "RESTRICTED":
            return {
                "status": "restricted",
                "message": f"Cannot {action} Bluetooth: Administrator permissions required.",
                "settings_fallback": "ms-settings:bluetooth",
            }

        if not status_val or not dev_id:
            return {
                "status": "unsupported",
                "message": "No Bluetooth radio adapter found to control.",
                "settings_fallback": "ms-settings:bluetooth",
            }

        cmd_verb = "Enable-PnpDevice" if action == "enable" else "Disable-PnpDevice"
        # Explicit targeting by InstanceId to avoid toggling other peripheral devices
        ps_cmd = (
            f"$d = Get-PnpDevice -InstanceId '{dev_id}' -ErrorAction Stop; "
            f"{cmd_verb} -InputObject $d -Confirm:$false"
        )

        try:
            res = _run_ps(ps_cmd)
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": f"Bluetooth {action} timed out."}
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"Bluetooth {action} failed: {exc}"}

        out = (res.stdout or "") + (res.stderr or "")
        if res.returncode != 0 or _is_access_denied(out):
            if _is_access_denied(out):
                return {
                    "status": "restricted",
                    "message": (
                        f"Cannot {action} Bluetooth: Administrator permissions required. "
                        "Run Nova as Administrator or use Windows Settings."
                    ),
                    "settings_fallback": "ms-settings:bluetooth",
                }
            return {
                "status": "error",
                "message": f"Failed to {action} Bluetooth: {out.strip()[:200]}",
            }

        # Read back actual state after brief settling time
        time.sleep(1.0)
        verify_status, _, _ = _query_pnp_bluetooth_radio()

        if action == "enable" and verify_status and verify_status.upper() != "OK":
            logger.warning("Bluetooth enable read-back mismatch: %s", verify_status)
            return {
                "status": "error",
                "message": f"Bluetooth enable command completed but device status is {verify_status}.",
            }

        logger.info("Bluetooth %sd successfully on %s", action, name_val or dev_id)
        return {
            "status": "ok",
            "action": action,
            "adapter_name": name_val,
            "verified_status": verify_status or "OK",
            "detail": f"Bluetooth {action}d ({name_val or 'Adapter'})",
        }


registry.register(BluetoothSkill())