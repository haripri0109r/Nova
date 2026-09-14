"""
Settings navigation skill – strictly handles Windows Settings page navigation.
"""

import logging
import os
import sys
import webbrowser
from typing import Any, Dict, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.settings")

# Explicit, centralized allowlist of supported Windows Settings URIs
SETTINGS_URI_MAP: Dict[str, str] = {
    "root": "ms-settings:",
    "settings": "ms-settings:",
    "display": "ms-settings:display",
    "sound": "ms-settings:sound",
    "notifications": "ms-settings:notifications",
    "power": "ms-settings:powersleep",
    "battery": "ms-settings:batterysaver",
    "storage": "ms-settings:storagesense",

    "bluetooth": "ms-settings:bluetooth",
    "printers": "ms-settings:printers",
    "mouse": "ms-settings:mousetouchpad",
    "wifi": "ms-settings:network-wifi",
    "ethernet": "ms-settings:network-ethernet",
    "airplane_mode": "ms-settings:network-airplanemode",
    "hotspot": "ms-settings:network-mobilehotspot",

    "personalization": "ms-settings:personalization",
    "background": "ms-settings:personalization-background",
    "colors": "ms-settings:personalization-colors",
    "dark_mode": "ms-settings:personalization-colors",
    "taskbar": "ms-settings:taskbar",

    "apps": "ms-settings:appsfeatures",
    "default_apps": "ms-settings:defaultapps",
    "startup_apps": "ms-settings:startupapps",

    "windows_update": "ms-settings:windowsupdate",
    "date_time": "ms-settings:dateandtime",
}

# Deterministic alias mapping to canonical keys in SETTINGS_URI_MAP
SETTINGS_ALIASES: Dict[str, str] = {
    "screen": "display",
    "audio": "sound",
    "volume": "sound",
    "browser": "default_apps",
    "default_browser": "default_apps",
    "default apps": "default_apps",
    "defaults": "default_apps",
    "update": "windows_update",
    "updates": "windows_update",
    "date": "date_time",
    "time": "date_time",
    "datetime": "date_time",
    "date & time": "date_time",
    "powersleep": "power",
    "power & sleep": "power",
    "battery_saver": "battery",
    "battery saver": "battery",
    "storage_sense": "storage",
    "storage sense": "storage",
    "airplane": "airplane_mode",
    "airplanemode": "airplane_mode",
    "airplane mode": "airplane_mode",
    "mobile_hotspot": "hotspot",
    "mobile hotspot": "hotspot",
    "theme": "personalization",
    "wallpaper": "background",
    "darkmode": "dark_mode",
    "dark mode": "dark_mode",
    "color": "colors",
    "installed_apps": "apps",
    "installed apps": "apps",
    "startup": "startup_apps",
    "startup apps": "startup_apps",
    "main": "root",
}


def resolve_settings_page(page: str) -> Optional[str]:
    """Normalize page string and resolve against aliases and allowlist. Returns None if invalid/unsupported."""
    if not isinstance(page, str) or not page.strip():
        return None
    cleaned = page.strip().lower().replace("-", "_")

    # Direct match in allowlist
    if cleaned in SETTINGS_URI_MAP:
        return cleaned

    # Match with spaces replaced by underscore
    with_underscores = cleaned.replace(" ", "_")
    if with_underscores in SETTINGS_URI_MAP:
        return with_underscores

    # Check normalized alias map
    if cleaned in SETTINGS_ALIASES:
        target = SETTINGS_ALIASES[cleaned]
        if target in SETTINGS_URI_MAP:
            return target
    if with_underscores in SETTINGS_ALIASES:
        target = SETTINGS_ALIASES[with_underscores]
        if target in SETTINGS_URI_MAP:
            return target

    # Try removing trailing 'settings' or 'page' (e.g., 'display settings' -> 'display')
    for suffix in (" settings", "_settings", " page", "_page"):
        if cleaned.endswith(suffix):
            base = cleaned[:-len(suffix)].strip().replace(" ", "_")
            if base in SETTINGS_URI_MAP:
                return base
            if base in SETTINGS_ALIASES and SETTINGS_ALIASES[base] in SETTINGS_URI_MAP:
                return SETTINGS_ALIASES[base]

    return None


def get_settings_uri(page: str) -> Optional[str]:
    """Retrieve canonical ms-settings: URI for an allowlisted page name, or None if invalid."""
    resolved = resolve_settings_page(page)
    if not resolved:
        return None
    return SETTINGS_URI_MAP.get(resolved)



class SettingsSkill(BaseSkill):
    """
    Windows Settings Navigation Skill.
    Strictly handles navigating to Windows Settings pages via allowlisted ms-settings: URIs.
    Never mutates system state, never accepts arbitrary URI strings, and never executes shell commands.
    """
    intent = "open_settings"
    description = "Navigate to Windows Settings pages using allowlisted URIs."

    parameters_schema = {
        "type": "object",
        "properties": {
            "page": {
                "type": "string",
                "description": "Specific Windows Settings page to navigate to (e.g., 'display', 'sound', 'wifi', 'default_apps').",
            }
        },
        "required": ["page"],
        "additionalProperties": False,
    }

    def validate(self, parameters: Dict[str, Any]) -> bool:
        """Validate input parameters against schema."""
        if not isinstance(parameters, dict):
            raise ValueError("Parameters must be a dictionary")
        if "page" not in parameters:
            raise ValueError("SettingsSkill: missing required 'page' parameter")
        if not isinstance(parameters["page"], str):
            raise ValueError("SettingsSkill: 'page' must be a string")
        for k in parameters:
            if k != "page":
                raise ValueError(f"SettingsSkill: Unexpected parameter '{k}' (additional properties not allowed)")
        return True

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("open_settings", "settings")

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        raw_page = intent_data.get("page")
        if not raw_page:
            raw_page = "root"

        if not isinstance(raw_page, str):
            return {
                "success": False,
                "status": "failed",
                "message": "Invalid page parameter: must be a string",
                "detail": "Invalid page parameter: must be a string",
            }

        canonical_page = resolve_settings_page(raw_page)
        if not canonical_page or canonical_page not in SETTINGS_URI_MAP:
            supported = sorted(k for k in SETTINGS_URI_MAP.keys() if k not in ("root", "settings"))
            msg = f"Unknown or unsupported settings page '{raw_page}'. Supported pages: {', '.join(supported)}"
            return {
                "success": False,
                "status": "unsupported",
                "page": raw_page,
                "message": msg,
                "detail": msg,
                "available_pages": supported,
            }

        # Canonical URI is derived EXCLUSIVELY from the hardcoded allowlist
        target_uri = SETTINGS_URI_MAP[canonical_page]

        try:
            # Safe execution: os.startfile on Windows, webbrowser fallback for non-win32/test
            if sys.platform == "win32" and hasattr(os, "startfile"):
                os.startfile(target_uri)
            else:
                webbrowser.open(target_uri)

            logger.info("Navigated to Windows Settings: %s (%s)", canonical_page, target_uri)

            note = ""
            if canonical_page == "default_apps":
                note = (
                    "Windows default browser and app associations are protected by UserChoice hashes from programmatic background changes; "
                    "Settings has been opened for you to select your preferred defaults manually."
                )
                msg = "Opened Windows Settings for default apps. Note: default apps are protected by Windows UserChoice; please select in Settings."
            else:
                msg = f"Opened Windows Settings for {canonical_page}."

            res = {
                "success": True,
                "status": "opened",
                "action": "navigated",
                "page": canonical_page,
                "uri": target_uri,
                "target_uri": target_uri,
                "message": msg,
                "detail": msg,
            }
            if note:
                res["note"] = note
            return res
        except Exception as exc:
            logger.exception("Failed to navigate to settings page %s: %s", canonical_page, exc)
            msg = f"Failed to open Windows Settings for '{canonical_page}': {exc}"
            return {
                "success": False,
                "status": "failed",
                "page": canonical_page,
                "uri": target_uri,
                "target_uri": target_uri,
                "message": msg,
                "detail": msg,
            }


registry.register(SettingsSkill())