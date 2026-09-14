"""
User Application Detector.

Canonical capability for inspecting currently open user-facing applications
on Windows, used for safety checks such as shutdown preconditions.

Rules:
- Native Windows APIs (user32, dwmapi) via WindowSkill infrastructure.
- Read-only inspection: NEVER close applications, kill processes, or call taskkill.
- Exclude Windows/system infrastructure, background services, shell UI, and Nova itself.
- Deduplicate multiple windows belonging to the same application.
- Produce human-readable application names.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any, Dict, List, Optional, Set

from nova.skills.system.window import (
    WNDENUMPROC,
    _enumerate_windows,
    _get_user32,
    _get_window_process_name,
    _get_window_text,
    _is_valid_top_level_window,
)

logger = logging.getLogger("nova.skills.system.app_detector")

# ---------------------------------------------------------------------------
# Process & Window Filtering
# ---------------------------------------------------------------------------

#: Known Windows/system processes and background infrastructure to ignore
SYSTEM_PROCESSES: frozenset[str] = frozenset({
    "applicationframehost.exe",  # System wrapper; handled with custom logic
    "audiodg.exe",
    "conhost.exe",
    "csrss.exe",
    "ctfmon.exe",
    "dwm.exe",
    "fontdrvhost.exe",
    "lockapp.exe",
    "logonui.exe",
    "lsass.exe",
    "runtimebroker.exe",
    "searchhost.exe",
    "securityhealthservice.exe",
    "securityhealthsystray.exe",
    "services.exe",
    "shellexperiencehost.exe",
    "sihost.exe",
    "smartscreen.exe",
    "smss.exe",
    "spoolsv.exe",
    "startmenuexperiencehost.exe",
    "svchost.exe",
    "system",
    "systemsettings.exe",
    "taskhostw.exe",
    "textinputhost.exe",
    "wininit.exe",
    "winlogon.exe",
    "wlanext.exe",
})

#: Windows Explorer titles representing shell components rather than open folders
_SHELL_EXPLORER_TITLES: frozenset[str] = frozenset({
    "",
    "program manager",
    "task view",
    "task switching",
    "windows input experience",
})

#: Known process name -> Human-readable application display name
KNOWN_APP_NAMES: Dict[str, str] = {
    "chrome.exe": "Google Chrome",
    "code.exe": "Visual Studio Code",
    "spotify.exe": "Spotify",
    "notepad.exe": "Notepad",
    "msedge.exe": "Microsoft Edge",
    "discord.exe": "Discord",
    "slack.exe": "Slack",
    "teams.exe": "Microsoft Teams",
    "winword.exe": "Microsoft Word",
    "excel.exe": "Microsoft Excel",
    "powerpnt.exe": "Microsoft PowerPoint",
    "outlook.exe": "Microsoft Outlook",
    "windowsterminal.exe": "Windows Terminal",
    "calculatorapp.exe": "Calculator",
    "calc.exe": "Calculator",
    "vlc.exe": "VLC Media Player",
    "steam.exe": "Steam",
    "whatsapp.root.exe": "WhatsApp",
    "whatsapp.exe": "WhatsApp",
    "telegram.exe": "Telegram",
    "zoom.exe": "Zoom",
    "thunderbird.exe": "Thunderbird",
    "firefox.exe": "Mozilla Firefox",
    "brave.exe": "Brave Browser",
    "devenv.exe": "Visual Studio",
    "obs64.exe": "OBS Studio",
}


def _get_nova_pid() -> int:
    """Return the current process ID for Nova."""
    try:
        return os.getpid()
    except Exception:
        return -1


def _is_nova_process(proc_name: str, hwnd: int) -> bool:
    """Check if the given window belongs to Nova itself."""
    u32 = _get_user32()
    if u32 and u32.IsWindow(hwnd):
        import ctypes
        from ctypes import wintypes
        pid = wintypes.DWORD(0)
        u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == _get_nova_pid():
            return True

    clean_proc = (proc_name or "").lower().strip()
    if clean_proc in ("python.exe", "pythonw.exe", "py.exe", "nova.exe", "antigravity.exe", "antigravity ide.exe"):
        # Extra check: if title or process is Nova
        title = _get_window_text(hwnd).lower()
        if "nova" in title and "visual studio code" not in title and "chrome" not in title:
            return True
    return False


def _resolve_app_display_name(proc_name: str, title: str) -> str:
    """
    Resolve a human-readable display name for an application from process name and title.
    Never returns empty string for valid windows.
    """
    clean_proc = (proc_name or "").lower().strip()
    if clean_proc in KNOWN_APP_NAMES:
        return KNOWN_APP_NAMES[clean_proc]

    # Special handling for ApplicationFrameHost (UWP wrapper)
    if clean_proc == "applicationframehost.exe":
        if title:
            # UWP app title is typically the clean app name (e.g. "Calculator", "Weather")
            return title.split(" - ")[-1].strip() or "Application"
        return "Application"

    # Special handling for File Explorer
    if clean_proc == "explorer.exe":
        return "File Explorer"

    # Heuristic fallback: clean executable name without .exe
    base_name = clean_proc
    if base_name.endswith(".exe"):
        base_name = base_name[:-4]

    # Clean punctuation and capitalize
    words = base_name.replace("_", " ").replace("-", " ").split()
    if words:
        return " ".join(w.capitalize() for w in words)
    return title.strip() or "Application"


def _is_user_application(win: Dict[str, Any]) -> bool:
    """
    Determine if an enumerated window represents an open user-facing application.
    Filters out system processes, Windows shell, and Nova itself.
    """
    hwnd = win.get("hwnd", 0)
    proc = (win.get("process") or "").lower().strip()
    title = (win.get("title") or "").strip()

    # 1. Reject if no title or no process
    if not title or not proc:
        return False

    # 2. Reject Nova itself
    if _is_nova_process(proc, hwnd):
        return False

    # 3. Reject Windows infrastructure / system processes
    if proc in SYSTEM_PROCESSES:
        # Exception: ApplicationFrameHost with a genuine user app title (e.g. Calculator)
        if proc == "applicationframehost.exe" and title and title.lower() not in _SHELL_EXPLORER_TITLES:
            return True
        return False

    # 4. Reject Explorer shell (desktop / taskbar)
    if proc == "explorer.exe":
        if title.lower() in _SHELL_EXPLORER_TITLES:
            return False

    return True


def _enumerate_top_level_windows() -> List[Dict[str, Any]]:
    """
    Enumerate all valid top-level visible windows.
    Reuses WindowSkill's _enumerate_windows() and falls back to desktop enumeration
    if needed to ensure interactive desktop windows are found.
    """
    windows = _enumerate_windows()
    if windows:
        return windows

    if sys.platform != "win32":
        return []

    u32 = _get_user32()
    if not u32:
        return []

    # Fallback to interactive Default desktop enumeration
    desk_windows: List[Dict[str, Any]] = []
    try:
        hdesk = None
        if hasattr(u32, "OpenDesktopW"):
            hdesk = u32.OpenDesktopW("Default", 0, False, 0x01FF)
        if not hdesk and hasattr(u32, "OpenInputDesktop"):
            hdesk = u32.OpenInputDesktop(0, False, 0x01FF)

        if hdesk:
            def enum_cb(hwnd: int, lparam: int) -> bool:
                if _is_valid_top_level_window(hwnd):
                    t = _get_window_text(hwnd)
                    p = _get_window_process_name(hwnd)
                    is_min = bool(u32.IsIconic(hwnd))
                    is_max = bool(u32.IsZoomed(hwnd))
                    desk_windows.append({
                        "hwnd": hwnd,
                        "title": t,
                        "process": p,
                        "is_minimized": is_min,
                        "is_maximized": is_max,
                    })
                return True

            cb = WNDENUMPROC(enum_cb)
            u32.EnumDesktopWindows(hdesk, cb, 0)
            u32.CloseDesktop(hdesk)
            return desk_windows
    except Exception as exc:
        logger.debug("Desktop enumeration fallback failed: %s", exc)

    return []


def get_open_user_applications() -> List[Dict[str, Any]]:
    """
    Return a list of currently open user application windows.

    Each item contains:
    - hwnd: int
    - title: str
    - process: str
    - app_name: str (human-readable application display name)
    - is_minimized: bool
    - is_maximized: bool
    """
    all_windows = _enumerate_top_level_windows()
    user_apps = []

    for win in all_windows:
        if _is_user_application(win):
            app_name = _resolve_app_display_name(win.get("process", ""), win.get("title", ""))
            user_apps.append({
                **win,
                "app_name": app_name,
            })

    return user_apps


def check_shutdown_precondition() -> Dict[str, Any]:
    """
    Check if user applications are currently open before allowing shutdown.

    This function ONLY observes Windows state.
    It NEVER terminates processes, closes applications, or uses taskkill.

    Returns:
        {
            "ready": bool (True if no user applications are open, False otherwise),
            "open_applications": List[str] (deduplicated human-readable application names),
            "windows": List[Dict[str, Any]] (underlying window metadata)
        }
    """
    apps = get_open_user_applications()

    # Deduplicate application names preserving order
    seen: Set[str] = set()
    deduped_names: List[str] = []
    for app in apps:
        name = app["app_name"]
        if name and name not in seen:
            seen.add(name)
            deduped_names.append(name)

    is_ready = len(deduped_names) == 0

    return {
        "ready": is_ready,
        "open_applications": deduped_names,
        "windows": apps,
    }


# ---------------------------------------------------------------------------
# Message Formatting
# ---------------------------------------------------------------------------

def format_open_applications_list(apps: List[str]) -> str:
    """Format a list of application names into natural English with Oxford comma."""
    if not apps:
        return ""
    if len(apps) == 1:
        return apps[0]
    if len(apps) == 2:
        return f"{apps[0]} and {apps[1]}"
    if len(apps) <= 4:
        return f"{', '.join(apps[:-1])}, and {apps[-1]}"

    first_four = apps[:4]
    remaining_count = len(apps) - 4
    other_str = "application" if remaining_count == 1 else "applications"
    return f"{', '.join(first_four)}, and {remaining_count} other {other_str}"


def format_initial_blocked_message(apps: List[str]) -> str:
    """
    Format message when shutdown is initially blocked due to open applications.
    e.g. "Chrome, VS Code, Spotify, and Notepad are still open. Please close them and tell me when you're ready."
    """
    apps_str = format_open_applications_list(apps)
    verb = "is" if len(apps) == 1 else "are"
    pronoun = "it" if len(apps) == 1 else "them"
    return f"{apps_str} {verb} still open. Please close {pronoun} and tell me when you're ready."


def format_still_open_message(apps: List[str]) -> str:
    """
    Format message when user states applications are closed but they are still detected.
    e.g. "Chrome is still open. Please close it before I shut down."
    """
    apps_str = format_open_applications_list(apps)
    verb = "is" if len(apps) == 1 else "are"
    pronoun = "it" if len(apps) == 1 else "them"
    return f"{apps_str} {verb} still open. Please close {pronoun} before I shut down."
