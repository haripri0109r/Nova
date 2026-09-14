"""
Audio skill – master volume control, mute/unmute, audio endpoint enumeration,
microphone control, and default device management.
"""

import logging
import os
import sys
import webbrowser
from typing import Any, Dict, List, Optional, Tuple

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.audio")


# =============================================================================
# Helper Utilities & Core Audio Access
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


def _get_master_endpoint_volume():
    """Return the master playback IAudioEndpointVolume interface."""
    if sys.platform != "win32":
        return None
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        logger.error("pycaw not installed; audio control unavailable.")
        return None

    try:
        speakers = AudioUtilities.GetSpeakers()
        if hasattr(speakers, "EndpointVolume") and speakers.EndpointVolume:
            return speakers.EndpointVolume

        from pycaw.pycaw import IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        interface = speakers._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception as exc:
        logger.error("Failed to get master audio endpoint volume: %s", exc)
        return None


def _get_microphone_endpoint_volume():
    """Return the default recording IAudioEndpointVolume interface."""
    if sys.platform != "win32":
        return None
    try:
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
    except ImportError:
        logger.error("pycaw/comtypes not installed; microphone control unavailable.")
        return None

    try:
        mic = AudioUtilities.GetMicrophone()
        if not mic:
            return None
        if hasattr(mic, "EndpointVolume") and mic.EndpointVolume:
            return mic.EndpointVolume
        interface = mic.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception as exc:
        logger.debug("Failed to get microphone endpoint volume: %s", exc)
        return None


def _enumerate_devices(data_flow: int) -> List[Dict[str, Any]]:
    """
    Enumerate active audio endpoints.
    data_flow: 0 for eRender (playback/output), 1 for eCapture (recording/input).
    """
    if sys.platform != "win32":
        return []
    try:
        from pycaw.pycaw import AudioUtilities
        from pycaw.constants import DEVICE_STATE
        devices = AudioUtilities.GetAllDevices(data_flow, DEVICE_STATE.ACTIVE.value)
        res = []
        for d in devices:
            res.append({
                "name": getattr(d, "FriendlyName", "Unknown Device"),
                "id": getattr(d, "id", ""),
                "state": "active",
            })
        return res
    except Exception as exc:
        logger.error("Failed to enumerate audio devices (flow=%d): %s", data_flow, exc)
        return []


def resolve_device_name(query: str, devices: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Deterministically resolve a device query string against enumerated devices.
    Returns (matched_device_dict, error_message).
    Matching rules:
    1. Exact match (case-sensitive)
    2. Case-insensitive exact match
    3. Unique unambiguous substring match
    4. Ambiguous match -> explicit error with matching candidate names
    5. No match -> explicit error with available device names
    """
    if not query or not query.strip():
        return None, "Device name query cannot be empty."

    cleaned = query.strip()
    cleaned_lower = cleaned.lower()

    # 1. Exact match
    for d in devices:
        if d["name"] == cleaned:
            return d, None

    # 2. Case-insensitive exact match
    for d in devices:
        if d["name"].lower() == cleaned_lower:
            return d, None

    # 3. Substring match
    matches = []
    for d in devices:
        d_lower = d["name"].lower()
        if cleaned_lower in d_lower or d_lower in cleaned_lower:
            matches.append(d)

    if len(matches) == 1:
        return matches[0], None

    if len(matches) > 1:
        candidates = ", ".join(f"'{m['name']}'" for m in matches)
        return None, f"Ambiguous device name '{query}'. Did you mean: {candidates}?"

    available = ", ".join(f"'{d['name']}'" for d in devices) if devices else "None"
    return None, f"No audio device found matching '{query}'. Available active devices: {available}"


# =============================================================================
# AudioSkill Implementation
# =============================================================================

class AudioSkill(BaseSkill):
    """
    Canonical Windows Audio Control Skill.
    Handles master volume, mute/unmute, device enumeration (output & input),
    microphone volume and mute, and honest default device management.
    """
    intent = "audio"
    description = "Control Windows audio (volume, mute, list devices, microphone volume/mute, default device)."

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "get_volume",
                    "set_volume",
                    "increase_volume",
                    "decrease_volume",
                    "mute",
                    "unmute",
                    "list_outputs",
                    "list_inputs",
                    "get_mic_status",
                    "set_mic_volume",
                    "mute_mic",
                    "unmute_mic",
                    "set_default_output",
                ],
                "description": "Audio action to perform.",
            },
            "level": {
                "type": "integer",
                "description": "Target volume level (0 to 100) when setting volume.",
            },
            "amount": {
                "type": ["integer", "string"],
                "description": "Volume change amount or step ('small', 'medium', 'large').",
            },
            "device_name": {
                "type": "string",
                "description": "Target audio device name when switching default output.",
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
            raise ValueError("AudioSkill: missing required 'action' parameter")
        action = parameters.get("action")
        valid_actions = self.parameters_schema["properties"]["action"]["enum"]
        if action not in valid_actions:
            raise ValueError(f"AudioSkill: invalid action '{action}'. Must be one of {valid_actions}")

        allowed_keys = set(self.parameters_schema["properties"].keys())
        for k in parameters:
            if k not in allowed_keys:
                raise ValueError(f"AudioSkill: Unexpected parameter '{k}' (additional properties not allowed)")

        if action in ("set_volume", "set_mic_volume"):
            if "level" not in parameters:
                raise ValueError(f"AudioSkill: '{action}' requires 'level' parameter")
            level = parameters.get("level")
            if not isinstance(level, (int, float)):
                raise ValueError(f"AudioSkill: 'level' must be an integer, got {type(level).__name__}")
            if int(level) < 0 or int(level) > 100:
                raise ValueError(f"AudioSkill: 'level' must be between 0 and 100, got {level}")

        elif action == "set_default_output":
            if "device_name" not in parameters:
                raise ValueError("AudioSkill: 'set_default_output' requires 'device_name' parameter")
            device_name = parameters.get("device_name")
            if not isinstance(device_name, str) or not device_name.strip():
                raise ValueError("AudioSkill: 'device_name' must be a non-empty string")

        return True

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("audio", "set_volume", "volume", "audio_control")

    # -------------------------------------------------------------------------
    # Master Volume Handlers
    # -------------------------------------------------------------------------

    def _get_volume(self) -> Dict[str, Any]:
        """Read master volume level and mute state."""
        endpoint = _get_master_endpoint_volume()
        if endpoint is None:
            return {"status": "error", "message": "Master audio endpoint not available."}

        try:
            scalar = endpoint.GetMasterVolumeLevelScalar()
            vol = int(round(scalar * 100))
            is_muted = bool(endpoint.GetMute())
            mute_str = " (muted)" if is_muted else ""
            msg = f"Master volume is {vol}%{mute_str}."
            return {
                "status": "ok",
                "action": "get_volume",
                "volume": vol,
                "muted": is_muted,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to get master volume: %s", exc)
            return {"status": "error", "message": f"Failed to get master volume: {exc}"}

    def _set_volume(self, level: int) -> Dict[str, Any]:
        """Set master volume with read-back verification."""
        endpoint = _get_master_endpoint_volume()
        if endpoint is None:
            return {"status": "error", "message": "Master audio endpoint not available."}

        target = max(0, min(100, int(level)))
        try:
            endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
            
            # Read-back verification
            actual_scalar = endpoint.GetMasterVolumeLevelScalar()
            actual_vol = int(round(actual_scalar * 100))
            verified = abs(actual_vol - target) <= 1

            msg = f"Volume set to {actual_vol}%."
            if verified:
                msg = f"Volume set to {actual_vol}% (verified)."

            return {
                "status": "ok",
                "action": "set_volume",
                "volume": actual_vol,
                "verified": verified,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to set master volume: %s", exc)
            return {"status": "error", "message": f"Failed to set master volume: {exc}"}

    def _adjust_volume(self, delta: int) -> Dict[str, Any]:
        """Adjust master volume by delta with read-back verification."""
        endpoint = _get_master_endpoint_volume()
        if endpoint is None:
            return {"status": "error", "message": "Master audio endpoint not available."}

        try:
            current_scalar = endpoint.GetMasterVolumeLevelScalar()
            current = int(round(current_scalar * 100))
            target = max(0, min(100, current + delta))
            endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)

            actual_scalar = endpoint.GetMasterVolumeLevelScalar()
            actual_vol = int(round(actual_scalar * 100))

            action_word = "increased" if delta > 0 else "decreased"
            msg = f"Volume {action_word} by {abs(delta)}% (now {actual_vol}%)."
            return {
                "status": "ok",
                "action": f"{action_word}_volume",
                "volume": actual_vol,
                "delta": delta,
                "verified": True,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to adjust master volume: %s", exc)
            return {"status": "error", "message": f"Failed to adjust volume: {exc}"}

    def _set_mute(self, mute_flag: bool) -> Dict[str, Any]:
        """Mute or unmute master volume with read-back verification."""
        endpoint = _get_master_endpoint_volume()
        if endpoint is None:
            return {"status": "error", "message": "Master audio endpoint not available."}

        try:
            val = 1 if mute_flag else 0
            endpoint.SetMute(val, None)

            actual_mute = bool(endpoint.GetMute())
            verified = (actual_mute == mute_flag)

            action_name = "mute" if mute_flag else "unmute"
            msg = f"Volume {'muted' if mute_flag else 'unmuted'}."
            return {
                "status": "ok",
                "action": action_name,
                "muted": actual_mute,
                "verified": verified,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to set mute: %s", exc)
            return {"status": "error", "message": f"Failed to set mute: {exc}"}

    # -------------------------------------------------------------------------
    # Device Enumeration Handlers
    # -------------------------------------------------------------------------

    def _list_outputs(self) -> Dict[str, Any]:
        """List active audio output (playback) devices."""
        # eRender = 0
        devices = _enumerate_devices(0)
        names = [d["name"] for d in devices]
        names_str = ", ".join(names) if names else "None"
        msg = f"Active output audio devices ({len(devices)}): {names_str}."
        return {
            "status": "ok",
            "action": "list_outputs",
            "count": len(devices),
            "devices": devices,
            "message": msg,
            "detail": msg,
        }

    def _list_inputs(self) -> Dict[str, Any]:
        """List active audio input (recording) devices."""
        # eCapture = 1
        devices = _enumerate_devices(1)
        names = [d["name"] for d in devices]
        names_str = ", ".join(names) if names else "None"
        msg = f"Active input audio devices ({len(devices)}): {names_str}."
        return {
            "status": "ok",
            "action": "list_inputs",
            "count": len(devices),
            "devices": devices,
            "message": msg,
            "detail": msg,
        }

    # -------------------------------------------------------------------------
    # Microphone Handlers
    # -------------------------------------------------------------------------

    def _get_mic_status(self) -> Dict[str, Any]:
        """Read default microphone volume level and mute status."""
        endpoint = _get_microphone_endpoint_volume()
        if endpoint is None:
            return {
                "status": "unsupported",
                "message": "No active microphone detected or microphone control is unavailable.",
                "detail": "No active microphone endpoint found.",
            }

        try:
            scalar = endpoint.GetMasterVolumeLevelScalar()
            vol = int(round(scalar * 100))
            is_muted = bool(endpoint.GetMute())
            mute_str = " (muted)" if is_muted else ""
            msg = f"Microphone volume is {vol}%{mute_str}."
            return {
                "status": "ok",
                "action": "get_mic_status",
                "volume": vol,
                "muted": is_muted,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to get microphone status: %s", exc)
            return {"status": "error", "message": f"Failed to get microphone status: {exc}"}

    def _set_mic_volume(self, level: int) -> Dict[str, Any]:
        """Set microphone volume with read-back verification."""
        endpoint = _get_microphone_endpoint_volume()
        if endpoint is None:
            return {
                "status": "unsupported",
                "message": "No active microphone detected or microphone control is unavailable.",
            }

        target = max(0, min(100, int(level)))
        try:
            endpoint.SetMasterVolumeLevelScalar(target / 100.0, None)
            actual_scalar = endpoint.GetMasterVolumeLevelScalar()
            actual_vol = int(round(actual_scalar * 100))
            verified = abs(actual_vol - target) <= 1

            msg = f"Microphone volume set to {actual_vol}%."
            if verified:
                msg = f"Microphone volume set to {actual_vol}% (verified)."

            return {
                "status": "ok",
                "action": "set_mic_volume",
                "volume": actual_vol,
                "verified": verified,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to set microphone volume: %s", exc)
            return {"status": "error", "message": f"Failed to set microphone volume: {exc}"}

    def _set_mic_mute(self, mute_flag: bool) -> Dict[str, Any]:
        """Mute or unmute default microphone with read-back verification."""
        endpoint = _get_microphone_endpoint_volume()
        if endpoint is None:
            return {
                "status": "unsupported",
                "message": "No active microphone detected or microphone control is unavailable.",
            }

        try:
            val = 1 if mute_flag else 0
            endpoint.SetMute(val, None)
            actual_mute = bool(endpoint.GetMute())
            verified = (actual_mute == mute_flag)

            action_name = "mute_mic" if mute_flag else "unmute_mic"
            msg = f"Microphone {'muted' if mute_flag else 'unmuted'}."
            return {
                "status": "ok",
                "action": action_name,
                "muted": actual_mute,
                "verified": verified,
                "message": msg,
                "detail": msg,
            }
        except Exception as exc:
            logger.exception("Failed to set microphone mute: %s", exc)
            return {"status": "error", "message": f"Failed to set microphone mute: {exc}"}

    # -------------------------------------------------------------------------
    # Default Output Device Handler (Honest Restriction & Navigation)
    # -------------------------------------------------------------------------

    def _set_default_output(self, device_query: str) -> Dict[str, Any]:
        """
        Handle switching default audio output device.
        Resolves device deterministically.
        Windows restricts background programmatic switching of default audio endpoints
        without user interaction in Windows Settings.
        Navigates to ms-settings:sound and returns honest capability limitation.
        """
        # 1. Enumerate active output devices
        active_devices = _enumerate_devices(0)
        if not active_devices:
            return {"status": "error", "message": "No active audio output devices found."}

        # 2. Resolve target device deterministically
        matched, err = resolve_device_name(device_query, active_devices)
        if err or not matched:
            return {
                "status": "error",
                "message": err or f"Could not resolve device '{device_query}'.",
                "available_devices": [d["name"] for d in active_devices],
            }

        resolved_name = matched["name"]
        target_uri = "ms-settings:sound"
        try:
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(target_uri)
            else:
                webbrowser.open(target_uri)
        except Exception as exc:
            logger.warning("Failed to open %s: %s", target_uri, exc)

        msg = (
            f"Windows restricts background programmatic switching of the default audio device. "
            f"Target device '{resolved_name}' was verified; opened Sound Settings for you to make the selection."
        )
        return {
            "status": "restricted",
            "action": "navigated",
            "target_device": resolved_name,
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
            # Backward-compatibility fallback for set_volume
            if intent_data.get("intent") in ("set_volume", "volume"):
                action = "set_volume"
            else:
                return {"status": "error", "message": "Missing required parameter 'action'"}

        clean_action = action.strip().lower()

        # Handle volume action aliases
        if clean_action == "set":
            clean_action = "set_volume"
        elif clean_action == "increase":
            clean_action = "increase_volume"
        elif clean_action == "decrease":
            clean_action = "decrease_volume"

        try:
            if clean_action == "get_volume":
                return self._get_volume()

            elif clean_action == "set_volume":
                level = intent_data.get("level")
                if level is None:
                    return {"status": "error", "message": "Missing 'level' parameter for set_volume"}
                return self._set_volume(int(level))

            elif clean_action in ("increase_volume", "decrease_volume"):
                amount = intent_data.get("amount")
                step = _parse_step_amount(amount, default=10)
                delta = -abs(step) if clean_action == "decrease_volume" else abs(step)
                return self._adjust_volume(delta)

            elif clean_action == "mute":
                return self._set_mute(True)

            elif clean_action == "unmute":
                return self._set_mute(False)

            elif clean_action == "list_outputs":
                return self._list_outputs()

            elif clean_action == "list_inputs":
                return self._list_inputs()

            elif clean_action == "get_mic_status":
                return self._get_mic_status()

            elif clean_action == "set_mic_volume":
                level = intent_data.get("level")
                if level is None:
                    return {"status": "error", "message": "Missing 'level' parameter for set_mic_volume"}
                return self._set_mic_volume(int(level))

            elif clean_action == "mute_mic":
                return self._set_mic_mute(True)

            elif clean_action == "unmute_mic":
                return self._set_mic_mute(False)

            elif clean_action == "set_default_output":
                dev_name = intent_data.get("device_name")
                if not dev_name or not isinstance(dev_name, str):
                    return {"status": "error", "message": "Missing 'device_name' parameter for set_default_output"}
                return self._set_default_output(dev_name)

            else:
                return {"status": "error", "message": f"Unknown audio action '{action}'"}

        except Exception as exc:
            logger.exception("AudioSkill execution failed: %s", exc)
            return {"status": "error", "message": f"Audio control failed: {exc}"}


# Register AudioSkill with global singleton
registry.register(AudioSkill())
