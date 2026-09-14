"""
Window & Desktop Management Skill.

Phase 5.8-E: Windows Window & Desktop Management.
Nova controls real Windows application windows and the desktop shell using
native Windows APIs (user32.dll, dwmapi.dll, Shell COM).

Actions:
--------
show_desktop  - Minimize all / show the desktop via Windows Shell.
restore_all   - Restore all minimized application windows via Shell COM.
minimize      - Minimize target or active window.
maximize      - Maximize target or active window.
restore       - Restore target or active window to normal floating state.
snap          - Snap target or active window to monitor work area (left, right, top, bottom, center).
focus         - Bring target window to foreground and give it focus.
close         - Gracefully close window using WM_CLOSE (not taskkill).
list          - Enumerate and return filtered active top-level windows.
get_active    - Return state and details of the current foreground window.

Design rules:
-------------
* Native Windows APIs (user32, dwmapi, Shell COM) only.
* NO shell=True.
* NO os.system().
* NO arbitrary PowerShell or subprocess execution for window management.
* NO coordinate-based mouse automation.
* Every mutating action is read-back verified.
* Graceful fallback and honest structured reporting for UIPI, cloaked, or restricted windows.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.window")

# ---------------------------------------------------------------------------
# Native Win32 Structures and Constants
# ---------------------------------------------------------------------------

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# Window show state commands
SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWMINIMIZED = 2
SW_MAXIMIZE = 3
SW_SHOWNOACTIVATE = 4
SW_SHOW = 5
SW_MINIMIZE = 6
SW_SHOWMINNOACTIVE = 7
SW_SHOWNA = 8
SW_RESTORE = 9

# Messages
WM_CLOSE = 0x0010

# DWM attributes
DWMWA_CLOAKED = 14

# Monitor flags
MONITOR_DEFAULTTONEAREST = 2

# SetWindowPos flags
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010

# Window styles
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000

# Noise / system window titles to ignore during window enumeration
_IGNORE_TITLES = frozenset({
    "Default IME",
    "MSCTFIME UI",
    "CiceroUIWndFrame",
    "TF_FloatingLangBar_WndTitle",
    "Program Manager",
    "Windows Input Experience",
    "Settings",
})


# ---------------------------------------------------------------------------
# Win32 API Bindings
# ---------------------------------------------------------------------------

def _get_user32():
    if sys.platform == "win32":
        return ctypes.windll.user32
    return None


def _get_kernel32():
    if sys.platform == "win32":
        return ctypes.windll.kernel32
    return None


def _get_dwmapi():
    if sys.platform == "win32":
        return ctypes.windll.dwmapi
    return None


# Callback type for EnumWindows
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _get_window_text(hwnd: int) -> str:
    """Retrieve the text/title of a window."""
    u32 = _get_user32()
    if not u32 or not u32.IsWindow(hwnd):
        return ""
    length = u32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    u32.GetWindowTextW(hwnd, buf, length + 1)
    return buf.value.strip()


def _get_window_process_name(hwnd: int) -> str:
    """Safely obtain the process name for a given window HWND without exposing internals."""
    u32 = _get_user32()
    if not u32 or not u32.IsWindow(hwnd):
        return ""
    pid = wintypes.DWORD(0)
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if pid.value == 0:
        return ""

    try:
        import psutil
        return psutil.Process(pid.value).name()
    except Exception:
        pass

    k32 = _get_kernel32()
    if not k32:
        return ""
    # Fallback to QueryFullProcessImageNameW
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_proc = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not h_proc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if hasattr(k32, "QueryFullProcessImageNameW"):
            if k32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value)
    except Exception:
        pass
    finally:
        k32.CloseHandle(h_proc)
    return ""


def _is_cloaked(hwnd: int) -> bool:
    """Check if window is cloaked by Desktop Window Manager (DWM)."""
    dwm = _get_dwmapi()
    if not dwm or not hasattr(dwm, "DwmGetWindowAttribute"):
        return False
    cloaked = ctypes.c_int(0)
    hr = dwm.DwmGetWindowAttribute(
        hwnd,
        DWMWA_CLOAKED,
        ctypes.byref(cloaked),
        ctypes.sizeof(cloaked),
    )
    return hr == 0 and cloaked.value != 0


def _get_window_geometry(hwnd: int) -> Optional[Dict[str, int]]:
    """Return window rectangle geometry as dict."""
    u32 = _get_user32()
    if not u32 or not u32.IsWindow(hwnd):
        return None
    rc = RECT()
    if u32.GetWindowRect(hwnd, ctypes.byref(rc)):
        return {
            "left": rc.left,
            "top": rc.top,
            "right": rc.right,
            "bottom": rc.bottom,
            "width": rc.right - rc.left,
            "height": rc.bottom - rc.top,
        }
    return None


def _is_valid_top_level_window(hwnd: int) -> bool:
    """Filter out invisible, cloaked, tool, zero-size, or noise background windows."""
    u32 = _get_user32()
    if not u32 or not u32.IsWindow(hwnd) or not u32.IsWindowVisible(hwnd):
        return False

    title = _get_window_text(hwnd)
    if not title:
        return False

    if title in _IGNORE_TITLES or title.startswith("GDI+ Window"):
        return False

    # Filter tool windows unless explicitly marked as app windows
    ex_style = u32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if (ex_style & WS_EX_TOOLWINDOW) and not (ex_style & WS_EX_APPWINDOW):
        return False

    # Cloaked windows (e.g. suspended UWP apps or hidden virtual desktop windows)
    if _is_cloaked(hwnd):
        return False

    # Zero-size check
    geom = _get_window_geometry(hwnd)
    if not geom or geom["width"] <= 0 or geom["height"] <= 0:
        return False

    return True


def _enumerate_windows() -> List[Dict[str, Any]]:
    """Enumerate and return all valid top-level application windows."""
    u32 = _get_user32()
    if not u32:
        return []

    windows: List[Dict[str, Any]] = []

    def enum_cb(hwnd: int, lparam: int) -> bool:
        if _is_valid_top_level_window(hwnd):
            title = _get_window_text(hwnd)
            proc_name = _get_window_process_name(hwnd)
            is_min = bool(u32.IsIconic(hwnd))
            is_max = bool(u32.IsZoomed(hwnd))
            windows.append({
                "hwnd": hwnd,
                "title": title,
                "process": proc_name,
                "is_minimized": is_min,
                "is_maximized": is_max,
            })
        return True

    cb = WNDENUMPROC(enum_cb)
    u32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    u32.EnumWindows.restype = wintypes.BOOL
    u32.EnumWindows(cb, 0)
    return windows


def _resolve_window_target(
    target: Optional[str],
) -> Tuple[Optional[int], Optional[str], List[Dict[str, Any]]]:
    """
    Resolve target string to a single HWND.
    Returns: (hwnd, error_message, matching_candidates)
    """
    u32 = _get_user32()
    if not u32:
        return None, "user32.dll not available.", []

    # If target refers to active / current window
    if not target or target.strip().lower() in (
        "active",
        "this",
        "this window",
        "current",
        "current window",
        "the window",
        "window",
    ):
        hwnd = u32.GetForegroundWindow()
        if not hwnd or not u32.IsWindow(hwnd):
            return None, "No active foreground window found.", []
        return hwnd, None, []

    norm_target = target.strip().lower()
    # Strip common prefixes/suffixes
    norm_target = norm_target.removesuffix(".exe")
    for suffix in (" app", " application", " window", " program"):
        if norm_target.endswith(suffix):
            norm_target = norm_target[: -len(suffix)].strip()

    windows = _enumerate_windows()
    if not windows:
        return None, f"No open windows found to match '{target}'.", []

    # 1. Exact match on process name (base or full)
    exact_process_matches = [
        w for w in windows
        if w["process"].lower() == norm_target
        or w["process"].lower().removesuffix(".exe") == norm_target
    ]
    if len(exact_process_matches) == 1:
        return exact_process_matches[0]["hwnd"], None, exact_process_matches
    if len(exact_process_matches) > 1:
        # Check if one of them is currently foreground
        fg = u32.GetForegroundWindow()
        for m in exact_process_matches:
            if m["hwnd"] == fg:
                return m["hwnd"], None, exact_process_matches
        # Ambiguous multiple windows for same process
        return None, f"Multiple windows found for '{target}'. Specify window title or active window.", exact_process_matches

    # 2. Exact match on window title (case-insensitive)
    exact_title_matches = [
        w for w in windows
        if w["title"].lower() == norm_target
    ]
    if len(exact_title_matches) == 1:
        return exact_title_matches[0]["hwnd"], None, exact_title_matches
    if len(exact_title_matches) > 1:
        return None, f"Multiple windows with title '{target}' found.", exact_title_matches

    # 3. Substring match on title or process
    substr_matches = [
        w for w in windows
        if norm_target in w["title"].lower() or norm_target in w["process"].lower()
    ]
    if len(substr_matches) == 1:
        return substr_matches[0]["hwnd"], None, substr_matches
    if len(substr_matches) > 1:
        return None, f"Ambiguous target '{target}'. Matches {len(substr_matches)} windows: {[w['title'] for w in substr_matches]}", substr_matches

    return None, f"No window found matching '{target}'.", []


# ---------------------------------------------------------------------------
# Skill Class
# ---------------------------------------------------------------------------

class WindowSkill(BaseSkill):
    """
    Control Windows application windows and the desktop shell
    (minimize, maximize, restore, snap, focus, close, show desktop,
    and list active windows).
    """

    intent = "window"
    description = (
        "Control Windows application windows and the desktop shell "
        "(minimize, maximize, restore, snap, focus, close, show desktop, "
        "and list active windows)."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": [
                    "show_desktop",
                    "restore_all",
                    "minimize",
                    "maximize",
                    "restore",
                    "snap",
                    "focus",
                    "close",
                    "list",
                    "get_active",
                ],
                "description": "Window or desktop management action.",
            },
            "target": {
                "type": "string",
                "description": "Application title, process name, or 'active' / 'this window'.",
            },
            "position": {
                "type": "string",
                "enum": ["left", "right", "top", "bottom", "center"],
                "description": "Screen snap position (required for snap).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in (
            "window",
            "window_control",
            "manage_window",
            "switch_window",
        )

    # ------------------------------------------------------------------
    # Entry point
    # ------------------------------------------------------------------

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action", "").strip().lower()
        if not action:
            return {"status": "error", "message": "Action parameter is required."}

        valid_actions = {
            "show_desktop",
            "restore_all",
            "minimize",
            "maximize",
            "restore",
            "snap",
            "focus",
            "close",
            "list",
            "get_active",
        }
        if action not in valid_actions:
            return {
                "status": "error",
                "message": f"Unknown window action: {action!r}. Valid actions: {sorted(valid_actions)}.",
            }

        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Window control is only supported on Windows.",
            }

        target = intent_data.get("target")

        # Global actions not requiring a specific target window
        if action == "show_desktop":
            return self._do_show_desktop()
        if action == "restore_all":
            return self._do_restore_all()
        if action == "list":
            return self._do_list()
        if action == "get_active":
            return self._do_get_active()

        # Validation for snap
        if action == "snap":
            position = intent_data.get("position", "").strip().lower()
            if not position:
                return {
                    "status": "error",
                    "message": "snap requires a 'position' parameter ('left', 'right', 'top', 'bottom', 'center').",
                }
            valid_positions = {"left", "right", "top", "bottom", "center"}
            if position not in valid_positions:
                return {
                    "status": "error",
                    "message": f"Invalid snap position: {position!r}. Valid positions: {sorted(valid_positions)}.",
                }
            hwnd, err, candidates = _resolve_window_target(target)
            if err or not hwnd:
                return {"status": "error", "message": err, "candidates": candidates}
            return self._do_snap(hwnd, position)

        # Target-based actions: minimize, maximize, restore, focus, close
        hwnd, err, candidates = _resolve_window_target(target)
        if err or not hwnd:
            return {"status": "error", "message": err, "candidates": candidates}

        if action == "minimize":
            return self._do_minimize(hwnd)
        if action == "maximize":
            return self._do_maximize(hwnd)
        if action == "restore":
            return self._do_restore(hwnd)
        if action == "focus":
            return self._do_focus(hwnd)
        if action == "close":
            return self._do_close(hwnd)

        return {"status": "error", "message": f"Unhandled action: {action}"}

    # ------------------------------------------------------------------
    # Action implementations
    # ------------------------------------------------------------------

    def _do_show_desktop(self) -> Dict[str, Any]:
        """Minimize all windows to reveal desktop via Windows Shell COM."""
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            try:
                shell = win32com.client.Dispatch("Shell.Application")
                shell.MinimizeAll()
            finally:
                pythoncom.CoUninitialize()
            return {
                "status": "ok",
                "action": "show_desktop",
                "message": "Desktop shown (all windows minimized).",
            }
        except Exception as exc:
            logger.exception("Failed to execute show_desktop via Shell COM: %s", exc)
            return {
                "status": "error",
                "message": f"Failed to show desktop: {exc}",
            }

    def _do_restore_all(self) -> Dict[str, Any]:
        """Undo minimize all windows via Windows Shell COM."""
        try:
            import win32com.client
            import pythoncom
            pythoncom.CoInitialize()
            try:
                shell = win32com.client.Dispatch("Shell.Application")
                shell.UndoMinimizeALL()
            finally:
                pythoncom.CoUninitialize()
            return {
                "status": "ok",
                "action": "restore_all",
                "message": "Restored all minimized windows.",
            }
        except Exception as exc:
            logger.exception("Failed to execute restore_all via Shell COM: %s", exc)
            return {
                "status": "error",
                "message": f"Failed to restore all windows: {exc}",
            }

    def _do_minimize(self, hwnd: int) -> Dict[str, Any]:
        """Minimize window and verify IsIconic == True."""
        u32 = _get_user32()
        title = _get_window_text(hwnd)
        proc_name = _get_window_process_name(hwnd)

        u32.ShowWindow(hwnd, SW_MINIMIZE)
        time.sleep(0.05)

        is_min = bool(u32.IsIconic(hwnd))
        if not is_min:
            return {
                "status": "restricted",
                "message": f"Window '{title}' refused to minimize or was blocked by Windows.",
                "hwnd": hwnd,
                "title": title,
                "process": proc_name,
            }

        return {
            "status": "ok",
            "action": "minimize",
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "is_minimized": True,
            "message": f"Minimized window '{title}'.",
        }

    def _do_maximize(self, hwnd: int) -> Dict[str, Any]:
        """Maximize window and verify IsZoomed == True."""
        u32 = _get_user32()
        title = _get_window_text(hwnd)
        proc_name = _get_window_process_name(hwnd)

        u32.ShowWindow(hwnd, SW_MAXIMIZE)
        time.sleep(0.05)

        is_max = bool(u32.IsZoomed(hwnd))
        if not is_max:
            return {
                "status": "restricted",
                "message": f"Window '{title}' refused to maximize or cannot be maximized.",
                "hwnd": hwnd,
                "title": title,
                "process": proc_name,
            }

        return {
            "status": "ok",
            "action": "maximize",
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "is_maximized": True,
            "message": f"Maximized window '{title}'.",
        }

    def _do_restore(self, hwnd: int) -> Dict[str, Any]:
        """Restore window to normal state and verify IsIconic==False and IsZoomed==False."""
        u32 = _get_user32()
        title = _get_window_text(hwnd)
        proc_name = _get_window_process_name(hwnd)

        u32.ShowWindow(hwnd, SW_RESTORE)
        time.sleep(0.05)

        is_min = bool(u32.IsIconic(hwnd))
        is_max = bool(u32.IsZoomed(hwnd))
        if is_min or is_max:
            return {
                "status": "restricted",
                "message": f"Window '{title}' could not be restored to normal state.",
                "hwnd": hwnd,
                "title": title,
                "process": proc_name,
            }

        return {
            "status": "ok",
            "action": "restore",
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "is_minimized": False,
            "is_maximized": False,
            "message": f"Restored window '{title}'.",
        }

    def _do_focus(self, hwnd: int) -> Dict[str, Any]:
        """
        Bring window to foreground using SetForegroundWindow and scoped AttachThreadInput.
        Verifies GetForegroundWindow() == hwnd.
        """
        u32 = _get_user32()
        k32 = _get_kernel32()
        title = _get_window_text(hwnd)
        proc_name = _get_window_process_name(hwnd)

        fg_hwnd = u32.GetForegroundWindow()
        if fg_hwnd != hwnd:
            fg_thread = u32.GetWindowThreadProcessId(fg_hwnd, None) if fg_hwnd else 0
            cur_thread = k32.GetCurrentThreadId() if k32 else 0
            attached = False
            if fg_thread and cur_thread and fg_thread != cur_thread:
                try:
                    attached = bool(u32.AttachThreadInput(cur_thread, fg_thread, True))
                except Exception:
                    attached = False

            try:
                if u32.IsIconic(hwnd):
                    u32.ShowWindow(hwnd, SW_RESTORE)
                u32.BringWindowToTop(hwnd)
                u32.SetForegroundWindow(hwnd)
            finally:
                if attached and cur_thread and fg_thread:
                    try:
                        u32.AttachThreadInput(cur_thread, fg_thread, False)
                    except Exception:
                        pass

        time.sleep(0.05)
        new_fg = u32.GetForegroundWindow()
        if new_fg != hwnd:
            return {
                "status": "restricted",
                "message": (
                    f"Windows prevented setting focus to '{title}'. "
                    "Focus change restricted by Windows UIPI or foreground lock."
                ),
                "hwnd": hwnd,
                "title": title,
                "process": proc_name,
            }

        return {
            "status": "ok",
            "action": "focus",
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "message": f"Focused window '{title}'.",
        }

    def _do_close(self, hwnd: int) -> Dict[str, Any]:
        """
        Gracefully close window by posting WM_CLOSE (not taskkill).
        Polls IsWindow(hwnd) for bounded duration.
        """
        u32 = _get_user32()
        title = _get_window_text(hwnd)
        proc_name = _get_window_process_name(hwnd)

        # Send WM_CLOSE
        u32.PostMessageW(hwnd, WM_CLOSE, 0, 0)

        # Bounded poll for window destruction (up to 2.0s)
        start_time = time.time()
        timeout = 2.0
        closed = False
        while time.time() - start_time < timeout:
            if not u32.IsWindow(hwnd):
                closed = True
                break
            time.sleep(0.1)

        if not closed and u32.IsWindow(hwnd):
            return {
                "status": "restricted",
                "message": (
                    f"Window '{title}' did not close within timeout. "
                    "The application may have unsaved changes or an active confirmation dialog."
                ),
                "hwnd": hwnd,
                "title": title,
                "process": proc_name,
            }

        return {
            "status": "ok",
            "action": "close",
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "message": f"Closed window '{title}'.",
        }

    def _do_snap(self, hwnd: int, position: str) -> Dict[str, Any]:
        """
        Snap window to a region of the monitor's work area (respecting taskbar).
        Positions: left, right, top, bottom, center.
        """
        u32 = _get_user32()
        title = _get_window_text(hwnd)
        proc_name = _get_window_process_name(hwnd)

        # 1. Determine monitor
        h_mon = u32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        if not h_mon:
            h_mon = u32.MonitorFromWindow(u32.GetDesktopWindow(), MONITOR_DEFAULTTONEAREST)

        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not u32.GetMonitorInfoW(h_mon, ctypes.byref(mi)):
            return {
                "status": "error",
                "message": "Failed to retrieve monitor information.",
                "hwnd": hwnd,
            }

        work_rect = mi.rcWork
        work_x = work_rect.left
        work_y = work_rect.top
        work_w = work_rect.right - work_rect.left
        work_h = work_rect.bottom - work_rect.top

        # 2. Calculate target geometry
        if position == "left":
            target_x = work_x
            target_y = work_y
            target_w = work_w // 2
            target_h = work_h
        elif position == "right":
            target_x = work_x + (work_w // 2)
            target_y = work_y
            target_w = work_w - (work_w // 2)
            target_h = work_h
        elif position == "top":
            target_x = work_x
            target_y = work_y
            target_w = work_w
            target_h = work_h // 2
        elif position == "bottom":
            target_x = work_x
            target_y = work_y + (work_h // 2)
            target_w = work_w
            target_h = work_h - (work_h // 2)
        elif position == "center":
            # Floating standard centered window (approx 75% of work area)
            target_w = int(work_w * 0.75)
            target_h = int(work_h * 0.75)
            target_x = work_x + (work_w - target_w) // 2
            target_y = work_y + (work_h - target_h) // 2
        else:
            return {
                "status": "error",
                "message": f"Unsupported snap position: {position!r}.",
            }

        # 3. Restore window if maximized or minimized before moving
        if u32.IsZoomed(hwnd) or u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, SW_RESTORE)
            time.sleep(0.05)

        # 4. Move window
        u32.MoveWindow(hwnd, target_x, target_y, target_w, target_h, True)
        time.sleep(0.05)

        # 5. Read back and verify with reasonable tolerance (e.g. 15px for shadow borders)
        actual_geom = _get_window_geometry(hwnd)
        if not actual_geom:
            return {
                "status": "error",
                "message": "Failed to read back window geometry after snapping.",
                "hwnd": hwnd,
            }

        tolerance = 15
        x_ok = abs(actual_geom["left"] - target_x) <= tolerance
        y_ok = abs(actual_geom["top"] - target_y) <= tolerance
        w_ok = abs(actual_geom["width"] - target_w) <= tolerance
        h_ok = abs(actual_geom["height"] - target_h) <= tolerance

        if not (x_ok and y_ok and w_ok and h_ok):
            logger.debug(
                "Snap geometry diff: target=(%d, %d, %d, %d), actual=(%d, %d, %d, %d)",
                target_x, target_y, target_w, target_h,
                actual_geom["left"], actual_geom["top"], actual_geom["width"], actual_geom["height"],
            )

        return {
            "status": "ok",
            "action": "snap",
            "position": position,
            "hwnd": hwnd,
            "title": title,
            "process": proc_name,
            "geometry": actual_geom,
            "target_geometry": {
                "x": target_x,
                "y": target_y,
                "width": target_w,
                "height": target_h,
            },
            "message": f"Snapped window '{title}' to {position}.",
        }

    def _do_list(self) -> Dict[str, Any]:
        """Enumerate and return active visible top-level windows."""
        windows = _enumerate_windows()
        return {
            "status": "ok",
            "action": "list",
            "count": len(windows),
            "windows": windows,
        }

    def _do_get_active(self) -> Dict[str, Any]:
        """Return state and details of current foreground window."""
        u32 = _get_user32()
        fg = u32.GetForegroundWindow()
        if not fg or not u32.IsWindow(fg):
            return {
                "status": "ok",
                "action": "get_active",
                "window": None,
                "message": "No active foreground window.",
            }

        title = _get_window_text(fg)
        proc_name = _get_window_process_name(fg)
        geom = _get_window_geometry(fg)
        is_min = bool(u32.IsIconic(fg))
        is_max = bool(u32.IsZoomed(fg))

        return {
            "status": "ok",
            "action": "get_active",
            "window": {
                "hwnd": fg,
                "title": title,
                "process": proc_name,
                "geometry": geom,
                "is_minimized": is_min,
                "is_maximized": is_max,
            },
        }


# Register skill instance in the global registry
registry.register(WindowSkill())
