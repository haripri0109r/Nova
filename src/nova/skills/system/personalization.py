"""
Personalization skill – strictly handles Windows personalization state mutations.
Supports Theme (Dark/Light mode), Taskbar alignment (Left/Center), and Wallpaper.
"""

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

try:
    import winreg
except ImportError:
    winreg = None  # type: ignore

logger = logging.getLogger("nova.skills.system.personalization")

# Hardcoded, safe registry locations
THEME_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
TASKBAR_REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced"

# Win32 Constants
HWND_BROADCAST = 0xFFFF
WM_SETTINGCHANGE = 0x001A
SMTO_ABORTIFHUNG = 0x0002
SPI_SETDESKWALLPAPER = 20
SPIF_UPDATEINIFILE = 0x01
SPIF_SENDCHANGE = 0x02

ALLOWED_WALLPAPER_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp"}


def _broadcast_setting_change(param_str: str) -> None:
    """Safely notify Windows running shells and applications of a settings change."""
    if sys.platform != "win32":
        return
    try:
        result = ctypes.c_ulong()
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            param_str,
            SMTO_ABORTIFHUNG,
            1000,
            ctypes.byref(result),
        )
    except Exception as exc:
        logger.debug("Broadcast setting change failed: %s", exc)


class PersonalizationSkill(BaseSkill):
    """
    Windows Personalization Mutation Skill.
    Strictly handles actual state changes to Windows personalization (theme, taskbar, wallpaper).
    Never opens the Settings UI, never executes shell commands, and verifies mutations.
    """
    intent = "personalization"
    description = "Control Windows personalization (theme mode, taskbar alignment, wallpaper)."

    parameters_schema = {
        "type": "object",
        "properties": {
            "feature": {
                "type": "string",
                "enum": ["theme", "taskbar", "wallpaper"],
                "description": "Personalization feature to configure: 'theme', 'taskbar', or 'wallpaper'.",
            },
            "mode": {
                "type": "string",
                "enum": ["dark", "light"],
                "description": "Theme mode ('dark' or 'light') when feature is 'theme'.",
            },
            "alignment": {
                "type": "string",
                "enum": ["left", "center"],
                "description": "Taskbar alignment ('left' or 'center') when feature is 'taskbar'.",
            },
            "path": {
                "type": "string",
                "description": "Local image file path when feature is 'wallpaper'.",
            },
        },
        "required": ["feature"],
        "additionalProperties": False,
    }

    def validate(self, parameters: Dict[str, Any]) -> bool:
        """Validate input parameters against schema and feature requirements."""
        if not isinstance(parameters, dict):
            raise ValueError("Parameters must be a dictionary")
        if "feature" not in parameters:
            raise ValueError("PersonalizationSkill: missing required 'feature' parameter")
        feature = parameters.get("feature")
        if not isinstance(feature, str):
            raise ValueError(f"PersonalizationSkill: parameter 'feature' must be a string, got {type(feature).__name__}")
        if feature not in ("theme", "taskbar", "wallpaper"):
            raise ValueError(f"PersonalizationSkill: Invalid feature '{feature}'. Must be one of ['theme', 'taskbar', 'wallpaper']")
        for k in parameters:
            if k not in ("feature", "mode", "alignment", "path"):
                raise ValueError(f"PersonalizationSkill: Unexpected parameter '{k}' (additional properties not allowed)")
        if feature == "theme":
            mode = parameters.get("mode")
            if not isinstance(mode, str) or mode not in ("dark", "light"):
                raise ValueError(f"PersonalizationSkill: feature 'theme' requires 'mode' in ['dark', 'light'], got '{mode}'")
        elif feature == "taskbar":
            alignment = parameters.get("alignment")
            if not isinstance(alignment, str) or alignment not in ("left", "center"):
                raise ValueError(f"PersonalizationSkill: feature 'taskbar' requires 'alignment' in ['left', 'center'], got '{alignment}'")
        elif feature == "wallpaper":
            path_val = parameters.get("path")
            if not isinstance(path_val, str) or not path_val.strip():
                raise ValueError("PersonalizationSkill: feature 'wallpaper' requires non-empty string 'path'")
        return True

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("personalization", "set_personalization")

    def _broadcast_setting_change(self, param_str: str) -> None:
        """Delegate setting change broadcast to module function."""
        _broadcast_setting_change(param_str)

    def _set_theme_mode(self, mode: str) -> Tuple[bool, str]:
        """
        Set Windows Dark/Light mode in HKCU.
        dark: AppsUseLightTheme=0, SystemUsesLightTheme=0
        light: AppsUseLightTheme=1, SystemUsesLightTheme=1
        """
        if mode not in ("dark", "light"):
            return False, f"Invalid theme mode '{mode}': must be 'dark' or 'light'"

        target_val = 0 if mode == "dark" else 1

        if sys.platform != "win32":
            return True, f"Theme set to {mode} (simulated on non-Windows)"

        try:
            if winreg is None:
                return False, "winreg module is not available"

            # Open or create the Personalize key
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, THEME_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, target_val)
                winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, target_val)

            # Broadcast change
            self._broadcast_setting_change("ImmersiveColorSet")

            # Read-back verification
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, THEME_REG_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
                apps_val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
                sys_val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")

            if apps_val == target_val and sys_val == target_val:
                return True, f"Theme set to {mode} mode"
            else:
                return False, f"Verification failed: registry values did not reflect {mode} mode"

        except Exception as exc:
            logger.exception("Failed to set theme mode: %s", exc)
            return False, f"Failed to set theme mode: {exc}"

    def _set_taskbar_alignment(self, alignment: str) -> Tuple[bool, str]:
        """
        Set Windows 11 Taskbar alignment in HKCU.
        left: TaskbarAl=0
        center: TaskbarAl=1
        """
        if alignment not in ("left", "center"):
            return False, f"Invalid taskbar alignment '{alignment}': must be 'left' or 'center'"

        target_val = 0 if alignment == "left" else 1

        if sys.platform != "win32":
            return True, f"Taskbar alignment set to {alignment} (simulated on non-Windows)"

        try:
            if winreg is None:
                return False, "winreg module is not available"

            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, TASKBAR_REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, "TaskbarAl", 0, winreg.REG_DWORD, target_val)

            # Broadcast change so explorer repositions taskbar
            self._broadcast_setting_change("TraySettings")

            # Read-back verification
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, TASKBAR_REG_KEY, 0, winreg.KEY_QUERY_VALUE) as key:
                actual_val, _ = winreg.QueryValueEx(key, "TaskbarAl")

            if actual_val == target_val:
                return True, f"Taskbar aligned to {alignment}"
            else:
                return False, f"Verification failed: TaskbarAl is {actual_val}, expected {target_val}"

        except Exception as exc:
            logger.exception("Failed to set taskbar alignment: %s", exc)
            return False, f"Failed to set taskbar alignment: {exc}"

    def _set_wallpaper(self, path_str: str) -> Tuple[bool, str]:
        """
        Set desktop wallpaper using Win32 SystemParametersInfoW.
        Validates file existence, regular file, and allowed image extension.
        """
        if not isinstance(path_str, str) or not path_str.strip():
            return False, "Missing or empty wallpaper path"

        cleaned_path = path_str.strip().strip("\"'")

        # Security check: reject URLs, command strings, or suspicious characters
        lower_path = cleaned_path.lower()
        if any(lower_path.startswith(prefix) for prefix in ("http://", "https://", "ftp://", "file://")):
            return False, "Wallpaper path must be a local file path, not a URL"

        if any(c in cleaned_path for c in (";", "&", "|", "`", "$", "<", ">", "\n", "\r")):
            return False, "Wallpaper path contains invalid command characters"

        path_obj = Path(cleaned_path).expanduser()
        try:
            resolved = path_obj.resolve()
        except Exception as exc:
            return False, f"Invalid wallpaper path: {exc}"

        if not resolved.exists():
            return False, f"Wallpaper file not found: '{cleaned_path}'"

        if not resolved.is_file():
            return False, f"Wallpaper path is not a regular file: '{cleaned_path}'"

        is_transcoded = resolved.name.lower() == "transcodedwallpaper"
        if not is_transcoded and resolved.suffix.lower() not in ALLOWED_WALLPAPER_EXTENSIONS:
            return False, f"Unsupported wallpaper format '{resolved.suffix}'. Supported: {', '.join(sorted(ALLOWED_WALLPAPER_EXTENSIONS))}"

        if sys.platform != "win32":
            return True, f"Wallpaper set to {resolved} (simulated on non-Windows)"

        try:
            ret = ctypes.windll.user32.SystemParametersInfoW(
                SPI_SETDESKWALLPAPER,
                0,
                str(resolved),
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
            )
            if ret == 0:
                return False, "SystemParametersInfoW failed to set wallpaper"
            return True, f"Wallpaper updated to {resolved.name}"
        except Exception as exc:
            logger.exception("Failed to set wallpaper: %s", exc)
            return False, f"Failed to set wallpaper: {exc}"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        feature = intent_data.get("feature")
        if not feature or not isinstance(feature, str):
            return {"success": False, "status": "error", "message": "Missing required parameter 'feature'"}

        clean_feature = feature.strip().lower()

        if clean_feature == "theme":
            mode = intent_data.get("mode")
            if not mode or not isinstance(mode, str):
                return {"success": False, "status": "error", "message": "Feature 'theme' requires 'mode' ('dark' or 'light')"}
            clean_mode = mode.strip().lower()
            ok, msg = self._set_theme_mode(clean_mode)
            if ok:
                return {
                    "success": True,
                    "status": "ok",
                    "action": "mutated",
                    "feature": "theme",
                    "mode": clean_mode,
                    "verified": True,
                    "detail": msg,
                    "message": msg,
                }
            return {"success": False, "status": "error", "message": msg, "detail": msg}

        elif clean_feature == "taskbar":
            alignment = intent_data.get("alignment")
            if not alignment or not isinstance(alignment, str):
                return {"success": False, "status": "error", "message": "Feature 'taskbar' requires 'alignment' ('left' or 'center')"}
            clean_alignment = alignment.strip().lower()
            ok, msg = self._set_taskbar_alignment(clean_alignment)
            if ok:
                return {
                    "success": True,
                    "status": "ok",
                    "action": "mutated",
                    "feature": "taskbar",
                    "alignment": clean_alignment,
                    "verified": True,
                    "detail": msg,
                    "message": msg,
                }
            return {"success": False, "status": "error", "message": msg, "detail": msg}

        elif clean_feature == "wallpaper":
            path_str = intent_data.get("path")
            if not path_str or not isinstance(path_str, str):
                return {"success": False, "status": "error", "message": "Feature 'wallpaper' requires valid string 'path'"}
            ok, msg = self._set_wallpaper(path_str)
            if ok:
                return {
                    "success": True,
                    "status": "ok",
                    "action": "mutated",
                    "feature": "wallpaper",
                    "path": path_str,
                    "detail": msg,
                    "message": msg,
                }
            return {"success": False, "status": "error", "message": msg, "detail": msg}

        else:
            return {
                "success": False,
                "status": "error",
                "message": f"Unsupported personalization feature '{feature}'. Supported features: theme, taskbar, wallpaper",
                "detail": f"Unsupported personalization feature '{feature}'. Supported features: theme, taskbar, wallpaper",
            }


registry.register(PersonalizationSkill())
