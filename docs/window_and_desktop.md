# Phase 5.8-E: Windows Window & Desktop Management

## Overview

Nova provides native, direct control over Windows application windows and the desktop shell without relying on mouse coordinates, GUI automation tools, or PowerShell wrappers.

Nova interacts with Windows via `user32.dll`, `dwmapi.dll`, and Windows Shell COM (`Shell.Application`), verifying every state mutation and reporting honest, structured results.

---

## Canonical Skill: `WindowSkill`

- **Class**: `WindowSkill(BaseSkill)` (`src/nova/skills/system/window.py`)
- **Canonical Intent**: `window`
- **Aliases**: `window_control`, `manage_window`, `switch_window`
- **Supported Actions**:
  1. `show_desktop` — Minimize all windows and reveal the Windows desktop via Shell COM.
  2. `restore_all` — Restore all minimized application windows via Shell COM `UndoMinimizeALL`.
  3. `minimize` — Minimize target or active window (`ShowWindow(hwnd, SW_MINIMIZE)`).
  4. `maximize` — Maximize target or active window (`ShowWindow(hwnd, SW_MAXIMIZE)`).
  5. `restore` — Restore target or active window to normal floating state (`ShowWindow(hwnd, SW_RESTORE)`).
  6. `snap` — Snap target or active window to monitor work area (`left`, `right`, `top`, `bottom`, `center`).
  7. `focus` — Bring target window to foreground and activate it (`SetForegroundWindow(hwnd)`).
  8. `close` — Gracefully close window by posting `WM_CLOSE` (never `taskkill`).
  9. `list` — Enumerate and filter top-level application windows.
  10. `get_active` — Inspect and report the state of the current foreground window.

---

## Parameter Schema

The skill enforces a strict JSON Schema (`additionalProperties: False`):

```json
{
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
        "get_active"
      ],
      "description": "Window or desktop management action."
    },
    "target": {
      "type": "string",
      "description": "Application title, process name, or 'active' / 'this window'."
    },
    "position": {
      "type": "string",
      "enum": ["left", "right", "top", "bottom", "center"],
      "description": "Screen snap position (required for snap)."
    }
  },
  "required": ["action"],
  "additionalProperties": false
}
```

### Validation Invariants
- `snap` without `position` fails validation immediately.
- `target` is optional; if omitted or specified as `"active"` / `"this window"`, the operation targets the current foreground window (`GetForegroundWindow()`).
- Unrecognized actions or positions return descriptive structured error responses.

---

## Native Architecture & Windows APIs

### 1. Window Discovery & Enumeration (`user32.dll`, `dwmapi.dll`)
Top-level windows are enumerated using `user32.EnumWindows`. To prevent noise, the enumeration applies deterministic filters:
- **Visibility check**: `IsWindowVisible(hwnd)` must be true.
- **Title check**: `GetWindowTextLengthW(hwnd) > 0` (filters invisible worker/utility windows).
- **Tool window filter**: Windows with `WS_EX_TOOLWINDOW` and without `WS_EX_APPWINDOW` are ignored.
- **DWM Cloaking**: Suspended or virtual-desktop cloaked windows are detected via `DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED)` and excluded.
- **Zero-size filter**: Windows with zero width or zero height are excluded.
- **System noise**: Background infrastructure windows (e.g. `Default IME`, `MSCTFIME UI`, `CiceroUIWndFrame`, `Program Manager`) are excluded.

Process names are queried safely via `GetWindowThreadProcessId` combined with `psutil` or `QueryFullProcessImageNameW`, without exposing internal process memory.

### 2. Desktop Shell Management (`Shell.Application` COM)
- `show_desktop` executes `shell.MinimizeAll()` via `win32com.client.Dispatch("Shell.Application")`.
- `restore_all` executes `shell.UndoMinimizeALL()`, returning all previously minimized windows to their former arrangement.
- COM calls are isolated with `pythoncom.CoInitialize()` and `pythoncom.CoUninitialize()` for thread safety across execution contexts.

### 3. State Mutations & Verification (`user32.dll`)
Mutating actions read back and verify state using Win32 API queries:
- **Minimize**: `ShowWindow(hwnd, SW_MINIMIZE)` -> verified with `IsIconic(hwnd) == TRUE`.
- **Maximize**: `ShowWindow(hwnd, SW_MAXIMIZE)` -> verified with `IsZoomed(hwnd) == TRUE`.
- **Restore**: `ShowWindow(hwnd, SW_RESTORE)` -> verified with `not IsIconic(hwnd) and not IsZoomed(hwnd)`.

### 4. Window Snapping & Multi-Monitor Work Areas
Snapping targets the monitor where the window currently resides:
1. `MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)` determines the active display monitor.
2. `GetMonitorInfoW(hMonitor, ...)` retrieves the monitor's `rcWork` (work area rectangle).
3. The work area accounts for the taskbar (whether docked at the bottom, top, left, or right) and any desktop appbars.
4. If the window is currently maximized or minimized, it is restored before moving.
5. Calculated target rectangles:
   - `left`: `[work.left, work.top, work.width / 2, work.height]`
   - `right`: `[work.left + work.width / 2, work.top, work.width / 2, work.height]`
   - `top`: `[work.left, work.top, work.width, work.height / 2]`
   - `bottom`: `[work.left, work.top + work.height / 2, work.width, work.height / 2]`
   - `center`: Centered floating window sized to 75% of work area width and height.
6. Moved via `MoveWindow(hwnd, x, y, w, h, True)` and verified with `GetWindowRect(hwnd)`.

### 5. Focus & UIPI Foreground Restrictions
- Bringing a window to the foreground calls `SetForegroundWindow(hwnd)`.
- If the calling thread lacks foreground rights, Nova uses a temporary, scoped `AttachThreadInput` call to attach to the current foreground thread, activates the target, and immediately detaches.
- **Verification**: `GetForegroundWindow() == hwnd`.
- If Windows User Interface Privilege Isolation (UIPI) or foreground locks prevent activation (e.g. attempting to focus an elevated administrative window from a non-elevated prompt), Nova honestly returns:
  `{"status": "restricted", "message": "Windows prevented setting focus to '...'. Focus change restricted by Windows UIPI or foreground lock."}`.
- Nova never fakes focus success.

### 6. Graceful Window Close vs. Process Termination
- `WindowSkill` implements **window closure**, NOT process termination.
- Nova posts `PostMessageW(hwnd, WM_CLOSE, 0, 0)`.
- Nova polls `IsWindow(hwnd)` for a bounded period (up to 2.0 seconds).
- If the window closes, Nova returns `status="ok"`.
- If the application displays an "Unsaved changes — Save / Don't Save / Cancel" dialog or refuses to exit within the timeout, Nova does NOT force-kill the process. It honestly returns `status="restricted"` explaining that the window did not close and may have unsaved changes.
- Forceful process termination is reserved for `close_application` (`AppCloserSkill`), maintaining clear separation between window management and process killing.

---

## Brain & Anti-Greedy Intent Routing

The Brain classifier (`PlaceholderIntentClassifier`) integrates `IntentCategory.WINDOW` with strict boundaries:
- `"minimize all"`, `"show desktop"` -> `window/show_desktop`
- `"restore all"`, `"unminimize all"` -> `window/restore_all`
- `"minimize Chrome"`, `"minimize Spotify"`, `"minimize this"` -> `window/minimize`
- `"maximize Chrome"`, `"maximize this"` -> `window/maximize`
- `"restore Notepad"` -> `window/restore`
- `"switch to Chrome"`, `"bring Discord to front"`, `"focus Notepad"` -> `window/focus`
- `"snap Chrome to the left"`, `"snap this window right"` -> `window/snap`
- `"close this window"`, `"close Chrome window"` -> `window/close`
- `"what windows are open?"`, `"list open windows"` -> `window/list`
- `"what window is this?"`, `"what is the current window?"` -> `window/get_active`

### Anti-Greedy Guardrails
- `"open Chrome"` / `"launch Spotify"` -> preserved as `OPEN_APPLICATION` (never `window/focus`).
- `"search for Chrome"` -> preserved as `WEB_SEARCH` (never `window`).
- `"open WiFi settings"` -> preserved as `OPEN_SETTINGS` (never `window`).
- `"close Chrome application"` / `"close Chrome"` -> preserved as `CLOSE_APPLICATION`.
- Compound commands such as `"open Notepad and snap it to the left"` are detected and routed through LLM multi-step planning.

---

## Security & Reliability Rules

1. **Zero Shell Execution**: Window management contains no `shell=True`, no `os.system()`, no arbitrary PowerShell commands, and no subprocess launches.
2. **Read-Back Verification**: All state transitions (`IsIconic`, `IsZoomed`, `GetWindowRect`, `IsWindow`, `GetForegroundWindow`) are read back and verified before reporting success.
3. **No Fake Success**: UIPI restrictions, elevated windows, and timeout events report honest `"restricted"` or `"error"` statuses.
4. **Harmless Cleanup**: All tests clean up test windows (e.g. `notepad.exe`) in `try...finally` blocks.
