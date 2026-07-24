#!/usr/bin/env python3
"""
Concrete implementations of the voice commands.

All functions follow the signature: handler(text: str) -> None
They perform the action and log the outcome. Errors are logged but not raised.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional

from .commands import extract_generic_app

log = logging.getLogger("nova")


# -------------------------------------------------------------------------
# Helper: locate Chrome executable (reuse logic from automation.chrome)
# -------------------------------------------------------------------------
def _chrome_executable() -> Optional[str]:
    """Return path to chrome.exe or None if not found."""
    if sys.platform != "win32":
        return None
    import os
    import shutil

    for base in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
        os.environ.get("LOCALAPPDATA", ""),
    ):
        if not base:
            continue
        path = os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
        if os.path.isfile(path):
            return path
    return shutil.which("google-chrome") or shutil.which("chrome")


# -------------------------------------------------------------------------
# Helper: locate VS Code executable (mirrors cursor_editor logic)
# -------------------------------------------------------------------------
def _vscode_executable() -> Optional[str]:
    if sys.platform == "win32":
        import os
        local = os.environ.get("LOCALAPPDATA", "")
        for sub in (
            r"Programs\Microsoft VS Code\Code.exe",
            r"Programs\VS Code\Code.exe",
        ):
            if local:
                p = os.path.join(local, *sub.split("\\"))
                if os.path.isfile(p):
                    return p
    import shutil
    return shutil.which("code")


# -------------------------------------------------------------------------
# Command handlers
# -------------------------------------------------------------------------
def handle_open_chrome(_text: str) -> None:
    exe = _chrome_executable()
    if not exe:
        log.warning("Chrome not found; cannot open.")
        return
    try:
        subprocess.Popen([exe, "--new-window"], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        log.info("Opened Chrome.")
    except OSError as e:
        log.warning("Failed to launch Chrome: %s", e)


def handle_open_vscode(_text: str) -> None:
    exe = _vscode_executable()
    if not exe:
        log.warning("VS Code not found (install it or add `code` to PATH).")
        return
    try:
        subprocess.Popen([exe], creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        log.info("Opened VS Code.")
    except OSError as e:
        log.warning("Failed to launch VS Code: %s", e)


def _run_shutdown_command(args: list[str]) -> None:
    if sys.platform != "win32":
        log.warning("System power commands only implemented on Windows.")
        return
    try:
        subprocess.run([r"C:\Windows\System32\shutdown.exe"] + args, check=True)
        log.info("Executed shutdown command: %s", " ".join(args))
    except subprocess.CalledProcessError as e:
        log.error("Shutdown command failed: %s", e)


def handle_shutdown(_text: str) -> None:
    _run_shutdown_command(["/s", "/t", "0"])


def handle_restart(_text: str) -> None:
    _run_shutdown_command(["/r", "/t", "0"])


def handle_sleep(_text: str) -> None:
    if sys.platform != "win32":
        log.warning("Sleep command only implemented on Windows.")
        return
    try:
        subprocess.run(
            ["rundll32.exe", "powrprof.dll,SetSuspendState", "0", "1", "0"],
            check=True,
        )
        log.info("Sent sleep command.")
    except subprocess.CalledProcessError as e:
        log.error("Sleep command failed: %s", e)


# -------------------------------------------------------------------------
# Volume control via pycaw (Windows Core Audio API)
# -------------------------------------------------------------------------
def _get_audio_endpoint():
    """Return the default audio endpoint volume interface."""
    try:
        from pycaw.pycaw import AudioUtilities
    except ImportError:
        log.error("pycaw not installed; volume control unavailable.")
        return None

    devices = AudioUtilities.GetSpeakers()
    # pycaw 20251023+: EndpointVolume is already the activated IAudioEndpointVolume
    if hasattr(devices, 'EndpointVolume') and devices.EndpointVolume:
        return devices.EndpointVolume

    # Fallback for older pycaw versions
    try:
        from pycaw.pycaw import IAudioEndpointVolume
        from comtypes import CLSCTX_ALL
        interface = devices._dev.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)
    except Exception as exc:
        log.error("Failed to get audio endpoint: %s", exc)
        return None


def handle_mute_volume(_text: str) -> None:
    vol = _get_audio_endpoint()
    if vol is None:
        return
    try:
        vol.SetMute(1, None)
        log.info("System volume muted.")
    except Exception as e:
        log.error("Failed to mute volume: %s", e)


def _parse_volume_number(text: str) -> Optional[int]:
    """Extract an integer 0‑100 from text. Returns None if not found."""
    # look for digits
    m = re.search(r"\b(\d{1,3})\b", text)
    if m:
        val = int(m.group(1))
        return max(0, min(100, val))
    # simple word‑to‑number for common words
    word_map = {
        "zero": 0, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40,
        "fifty": 50, "sixty": 60, "seventy": 70, "eighty": 80, "ninety": 90,
        "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
        "six": 6, "seven": 7, "eight": 8, "nine": 9,
    }
    for w, v in word_map.items():
        if re.search(rf"\b{w}\b", text, re.IGNORECASE):
            return v
    return None


def handle_set_volume(text: str) -> None:
    vol = _get_audio_endpoint()
    if vol is None:
        return
    level = _parse_volume_number(text)
    if level is None:
        log.warning("Could not parse volume level from: %r", text)
        return
    try:
        # pycaw expects a float 0.0‑1.0
        vol.SetMasterVolumeLevelScalar(level / 100.0, None)
        log.info("Set system volume to %d%%.", level)
    except Exception as e:
        log.error("Failed to set volume: %s", e)


# -------------------------------------------------------------------------
# Brightness control via WMI (laptop panels only)
# -------------------------------------------------------------------------
def _adjust_brightness(delta: int) -> None:
    if sys.platform != "win32":
        log.warning("Brightness control only implemented on Windows.")
        return
    try:
        import wmi
    except ImportError:
        log.error("wmi package not installed; brightness control unavailable.")
        return

    c = wmi.WMI(namespace="wmi")
    methods = c.WmiMonitorBrightnessMethods()
    if not methods:
        log.warning("No WMI brightness methods found (external monitor?).")
        return
    # Get current brightness
    brightness_objs = c.WmiMonitorBrightness()
    if not brightness_objs:
        log.warning("Could not read current brightness.")
        return
    current = brightness_objs[0].CurrentBrightness
    target = max(0, min(100, current + delta))
    try:
        for m in methods:
            m.WmiSetBrightness(target, 0)
        log.info("Brightness changed from %d%% to %d%%.", current, target)
    except Exception as e:
        log.error("Failed to set brightness: %s", e)


def handle_increase_brightness(_text: str) -> None:
    from .config import settings
    _adjust_brightness(settings.nova_brightness_step)


def handle_decrease_brightness(_text: str) -> None:
    from .config import settings
    _adjust_brightness(-settings.nova_brightness_step)


# -------------------------------------------------------------------------
# Generic "open <app>" via Start‑Menu shortcuts
# -------------------------------------------------------------------------
_START_MENU_ROOTS = [
    Path(os.environ.get("ProgramData", r"C:\ProgramData"))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs",
    Path(os.environ.get("APPDATA", ""))
    / "Microsoft"
    / "Windows"
    / "Start Menu"
    / "Programs",
]


def _find_shortcut(app_name: str) -> list[Path]:
    """Return all *.lnk paths whose stem contains *app_name* (case‑insensitive)."""
    app_l = app_name.lower()
    matches = []
    for root in _START_MENU_ROOTS:
        if not root.is_dir():
            continue
        for lnk in root.rglob("*.lnk"):
            if app_l in lnk.stem.lower():
                matches.append(lnk)
    return matches


def handle_open_generic(text: str) -> None:
    """
    Generic "open <app> / launch <app>" handler.
    Delegates to AppLauncher (fuzzy matching + AppIndexer) instead of
    the old crude .lnk substring search.
    """
    # ------------------------------------------------------------------
    # 1️⃣  Extract the raw app name from the recognised utterance
    # ------------------------------------------------------------------
    app_name = extract_generic_app(text)
    if not app_name:
        log.warning("handle_open_generic called but no app name found")
        return

    # ------------------------------------------------------------------
    # 2️⃣  Delegate to AppLauncher (fuzzy match + AppIndexer)
    # ------------------------------------------------------------------
    from modules.launcher.app_launcher import get_app_launcher

    launcher = get_app_launcher()
    result = launcher.launch(app_name)

    # Map LaunchResult.status to appropriate log level / message
    if result.status == "launched":
        log.info("Opened %s", result.matched_app["name"])
    elif result.status == "ambiguous":
        names = ", ".join(c["name"] for c in result.candidates)
        log.warning("Ambiguous: %d apps match '%s' — %s", len(result.candidates), app_name, result.error_message)
    elif result.status == "not_found":
        log.warning("No app found matching '%s': %s", app_name, result.error_message)
    elif result.status == "error":
        log.error("Failed to launch '%s': %s", app_name, result.error_message)
    else:
        log.warning("Unexpected launch result for '%s': %s", app_name, result.status)


# -------------------------------------------------------------------------
# Mapping command name → handler
# -------------------------------------------------------------------------
COMMAND_HANDLERS = {
    "open_chrome": handle_open_chrome,
    "open_vscode": handle_open_vscode,
    "shutdown": handle_shutdown,
    "restart": handle_restart,
    "sleep": handle_sleep,
    "mute_volume": handle_mute_volume,
    "set_volume": handle_set_volume,
    "increase_brightness": handle_increase_brightness,
    "decrease_brightness": handle_decrease_brightness,
    "open_generic": handle_open_generic,
}

# Commands that require explicit spoken confirmation
DESTRUCTIVE_COMMANDS = {"shutdown", "restart", "sleep"}