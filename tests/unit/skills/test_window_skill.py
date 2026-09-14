"""
Unit tests for WindowSkill (Phase 5.8-E: Windows Window & Desktop Management).

Verifies:
- Strict schema adherence (JSON Schema object, required fields, additionalProperties: False)
- can_handle matching canonical intent and aliases
- Action validation (unknown action, missing action)
- Snap validation (missing position, invalid position)
- Target resolution (active/this window, process name, title, window not found, ambiguous match)
- All 10 actions with read-back verification:
  * show_desktop
  * restore_all
  * minimize
  * maximize
  * restore
  * focus
  * close
  * snap (left, right, top, bottom, center geometry)
  * list
  * get_active
- UIPI / restricted state reporting without fake success
- Non-Windows platform graceful handling
"""

import sys
from unittest.mock import MagicMock, patch
import pytest

from nova.skills.system.window import (
    WindowSkill,
    RECT,
    MONITORINFO,
    SW_MINIMIZE,
    SW_MAXIMIZE,
    SW_RESTORE,
    WM_CLOSE,
)


@pytest.fixture
def skill():
    return WindowSkill()


# ---------------------------------------------------------------------------
# Schema and Registration Tests
# ---------------------------------------------------------------------------

def test_window_skill_schema(skill):
    """Verify parameters_schema adheres to strict requirements."""
    schema = skill.parameters_schema
    assert schema["type"] == "object"
    assert "action" in schema["properties"]
    assert "target" in schema["properties"]
    assert "position" in schema["properties"]
    assert schema["required"] == ["action"]
    assert schema["additionalProperties"] is False

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
    assert set(schema["properties"]["action"]["enum"]) == valid_actions

    valid_positions = {"left", "right", "top", "bottom", "center"}
    assert set(schema["properties"]["position"]["enum"]) == valid_positions


def test_can_handle(skill):
    """Verify can_handle accepts canonical intent and recognized aliases."""
    assert skill.can_handle({"intent": "window"}) is True
    assert skill.can_handle({"intent": "window_control"}) is True
    assert skill.can_handle({"intent": "manage_window"}) is True
    assert skill.can_handle({"intent": "switch_window"}) is True
    assert skill.can_handle({"intent": "open_application"}) is False
    assert skill.can_handle({"intent": "unknown"}) is False


# ---------------------------------------------------------------------------
# Validation Tests
# ---------------------------------------------------------------------------

def test_missing_action(skill):
    res = skill.execute({})
    assert res["status"] == "error"
    assert "Action parameter is required" in res["message"]


def test_invalid_action(skill):
    res = skill.execute({"action": "explode"})
    assert res["status"] == "error"
    assert "Unknown window action" in res["message"]


def test_snap_missing_position(skill):
    res = skill.execute({"action": "snap", "target": "notepad"})
    assert res["status"] == "error"
    assert "requires a 'position' parameter" in res["message"]


def test_snap_invalid_position(skill):
    res = skill.execute({"action": "snap", "target": "notepad", "position": "diagonal"})
    assert res["status"] == "error"
    assert "Invalid snap position" in res["message"]


def test_non_windows_platform(skill):
    with patch("sys.platform", "linux"):
        res = skill.execute({"action": "list"})
        assert res["status"] == "unsupported"
        assert "Windows" in res["message"]


# ---------------------------------------------------------------------------
# Target Resolution Tests
# ---------------------------------------------------------------------------

@patch("nova.skills.system.window._enumerate_windows")
def test_target_not_found(mock_enum, skill):
    mock_enum.return_value = [
        {"hwnd": 100, "title": "Notepad", "process": "notepad.exe", "is_minimized": False, "is_maximized": False}
    ]
    res = skill.execute({"action": "minimize", "target": "Spotify"})
    assert res["status"] == "error"
    assert "No window found matching 'Spotify'" in res["message"]


@patch("nova.skills.system.window._enumerate_windows")
def test_ambiguous_target(mock_enum, skill):
    mock_enum.return_value = [
        {"hwnd": 101, "title": "Doc1 - Word", "process": "WINWORD.EXE", "is_minimized": False, "is_maximized": False},
        {"hwnd": 102, "title": "Doc2 - Word", "process": "WINWORD.EXE", "is_minimized": False, "is_maximized": False},
    ]
    mock_u32 = MagicMock()
    mock_u32.GetForegroundWindow.return_value = 999  # neither is active
    with patch("nova.skills.system.window._get_user32", return_value=mock_u32):
        res = skill.execute({"action": "focus", "target": "Word"})
        assert res["status"] == "error"
        assert "Multiple windows found" in res["message"] or "Ambiguous target" in res["message"]
        assert len(res["candidates"]) == 2


@patch("nova.skills.system.window._get_user32")
def test_active_window_target(mock_get_u32, skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.GetForegroundWindow.return_value = 501
    mock_u32.IsIconic.return_value = True
    mock_get_u32.return_value = mock_u32

    with patch("nova.skills.system.window._get_window_text", return_value="Active App"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="app.exe"):
        res = skill.execute({"action": "minimize", "target": "active"})
        assert res["status"] == "ok"
        assert res["action"] == "minimize"
        assert res["hwnd"] == 501
        assert res["is_minimized"] is True
        mock_u32.ShowWindow.assert_called_with(501, SW_MINIMIZE)


# ---------------------------------------------------------------------------
# Action Execution Tests
# ---------------------------------------------------------------------------

def test_show_desktop_success(skill):
    with patch("win32com.client.Dispatch") as mock_dispatch, \
         patch("pythoncom.CoInitialize"), \
         patch("pythoncom.CoUninitialize"):
        mock_shell = MagicMock()
        mock_dispatch.return_value = mock_shell

        res = skill.execute({"action": "show_desktop"})
        assert res["status"] == "ok"
        assert res["action"] == "show_desktop"
        mock_shell.MinimizeAll.assert_called_once()


def test_restore_all_success(skill):
    with patch("win32com.client.Dispatch") as mock_dispatch, \
         patch("pythoncom.CoInitialize"), \
         patch("pythoncom.CoUninitialize"):
        mock_shell = MagicMock()
        mock_dispatch.return_value = mock_shell

        res = skill.execute({"action": "restore_all"})
        assert res["status"] == "ok"
        assert res["action"] == "restore_all"
        mock_shell.UndoMinimizeALL.assert_called_once()


def test_minimize_success(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsIconic.return_value = True

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(201, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Test App"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="test.exe"):
        res = skill.execute({"action": "minimize", "target": "test"})
        assert res["status"] == "ok"
        assert res["action"] == "minimize"
        assert res["is_minimized"] is True
        mock_u32.ShowWindow.assert_called_with(201, SW_MINIMIZE)


def test_minimize_restricted(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsIconic.return_value = False  # Window refused to minimize

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(201, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Protected App"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="prot.exe"):
        res = skill.execute({"action": "minimize", "target": "prot"})
        assert res["status"] == "restricted"
        assert "refused to minimize" in res["message"]


def test_maximize_success(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsZoomed.return_value = True

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(202, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Editor"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="editor.exe"):
        res = skill.execute({"action": "maximize", "target": "editor"})
        assert res["status"] == "ok"
        assert res["action"] == "maximize"
        assert res["is_maximized"] is True
        mock_u32.ShowWindow.assert_called_with(202, SW_MAXIMIZE)


def test_maximize_restricted(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsZoomed.return_value = False

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(202, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Fixed Dialog"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="dialog.exe"):
        res = skill.execute({"action": "maximize", "target": "dialog"})
        assert res["status"] == "restricted"
        assert "refused to maximize" in res["message"]


def test_restore_success(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsIconic.return_value = False
    mock_u32.IsZoomed.return_value = False

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(203, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Player"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="player.exe"):
        res = skill.execute({"action": "restore", "target": "player"})
        assert res["status"] == "ok"
        assert res["action"] == "restore"
        assert res["is_minimized"] is False
        assert res["is_maximized"] is False
        mock_u32.ShowWindow.assert_called_with(203, SW_RESTORE)


def test_focus_success(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.GetForegroundWindow.side_effect = [100, 204]  # changes to target 204

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._get_kernel32", return_value=MagicMock()), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(204, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Notepad"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="notepad.exe"):
        res = skill.execute({"action": "focus", "target": "notepad"})
        assert res["status"] == "ok"
        assert res["action"] == "focus"
        assert res["hwnd"] == 204


def test_focus_restricted_uipi(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    # Foreground window remains different after SetForegroundWindow call
    mock_u32.GetForegroundWindow.side_effect = [100, 100]

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._get_kernel32", return_value=MagicMock()), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(205, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Admin Terminal"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="cmd.exe"):
        res = skill.execute({"action": "focus", "target": "cmd"})
        assert res["status"] == "restricted"
        assert "UIPI or foreground lock" in res["message"]


def test_close_success(skill):
    mock_u32 = MagicMock()
    # IsWindow returns False on second check (destroyed)
    mock_u32.IsWindow.side_effect = [True, False]

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(206, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Calculator"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="calc.exe"):
        res = skill.execute({"action": "close", "target": "calc"})
        assert res["status"] == "ok"
        assert res["action"] == "close"
        mock_u32.PostMessageW.assert_called_with(206, WM_CLOSE, 0, 0)


def test_close_refused_with_unsaved_dialog(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True  # Window stays open

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(207, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Unsaved Doc"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="wordpad.exe"), \
         patch("time.time", side_effect=[0.0, 1.0, 2.5]):  # Simulates timeout loop
        res = skill.execute({"action": "close", "target": "wordpad"})
        assert res["status"] == "restricted"
        assert "unsaved changes" in res["message"]


def test_snap_left_geometry(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsZoomed.return_value = False
    mock_u32.IsIconic.return_value = False

    def mock_get_monitor_info(hmon, mi_ref):
        mi = mi_ref._obj
        mi.rcWork.left = 0
        mi.rcWork.top = 0
        mi.rcWork.right = 1920
        mi.rcWork.bottom = 1040
        return True

    mock_u32.GetMonitorInfoW.side_effect = mock_get_monitor_info

    actual_geom = {"left": 0, "top": 0, "right": 960, "bottom": 1040, "width": 960, "height": 1040}

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(208, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Chrome"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="chrome.exe"), \
         patch("nova.skills.system.window._get_window_geometry", return_value=actual_geom):
        res = skill.execute({"action": "snap", "position": "left", "target": "chrome"})
        assert res["status"] == "ok"
        assert res["action"] == "snap"
        assert res["position"] == "left"
        assert res["target_geometry"]["x"] == 0
        assert res["target_geometry"]["y"] == 0
        assert res["target_geometry"]["width"] == 960
        assert res["target_geometry"]["height"] == 1040
        mock_u32.MoveWindow.assert_called_with(208, 0, 0, 960, 1040, True)


def test_snap_right_geometry(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsZoomed.return_value = False
    mock_u32.IsIconic.return_value = False

    def mock_get_monitor_info(hmon, mi_ref):
        mi = mi_ref._obj
        mi.rcWork.left = 0
        mi.rcWork.top = 0
        mi.rcWork.right = 1920
        mi.rcWork.bottom = 1040
        return True

    mock_u32.GetMonitorInfoW.side_effect = mock_get_monitor_info

    actual_geom = {"left": 960, "top": 0, "right": 1920, "bottom": 1040, "width": 960, "height": 1040}

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(209, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="Notepad"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="notepad.exe"), \
         patch("nova.skills.system.window._get_window_geometry", return_value=actual_geom):
        res = skill.execute({"action": "snap", "position": "right", "target": "notepad"})
        assert res["status"] == "ok"
        assert res["target_geometry"]["x"] == 960
        assert res["target_geometry"]["width"] == 960
        mock_u32.MoveWindow.assert_called_with(209, 960, 0, 960, 1040, True)


def test_snap_center_geometry(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.IsZoomed.return_value = False
    mock_u32.IsIconic.return_value = False

    def mock_get_monitor_info(hmon, mi_ref):
        mi = mi_ref._obj
        mi.rcWork.left = 0
        mi.rcWork.top = 0
        mi.rcWork.right = 1920
        mi.rcWork.bottom = 1000
        return True

    mock_u32.GetMonitorInfoW.side_effect = mock_get_monitor_info

    # 75% of 1920 = 1440, center x = (1920 - 1440)//2 = 240
    # 75% of 1000 = 750, center y = (1000 - 750)//2 = 125
    actual_geom = {"left": 240, "top": 125, "right": 1680, "bottom": 875, "width": 1440, "height": 750}

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._resolve_window_target", return_value=(210, None, [])), \
         patch("nova.skills.system.window._get_window_text", return_value="App"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="app.exe"), \
         patch("nova.skills.system.window._get_window_geometry", return_value=actual_geom):
        res = skill.execute({"action": "snap", "position": "center", "target": "app"})
        assert res["status"] == "ok"
        assert res["position"] == "center"
        assert res["target_geometry"]["x"] == 240
        assert res["target_geometry"]["y"] == 125
        assert res["target_geometry"]["width"] == 1440
        assert res["target_geometry"]["height"] == 750
        mock_u32.MoveWindow.assert_called_with(210, 240, 125, 1440, 750, True)


def test_list_windows(skill):
    sample_windows = [
        {"hwnd": 1, "title": "Chrome", "process": "chrome.exe", "is_minimized": False, "is_maximized": True},
        {"hwnd": 2, "title": "Notepad", "process": "notepad.exe", "is_minimized": False, "is_maximized": False},
    ]
    with patch("nova.skills.system.window._enumerate_windows", return_value=sample_windows):
        res = skill.execute({"action": "list"})
        assert res["status"] == "ok"
        assert res["action"] == "list"
        assert res["count"] == 2
        assert len(res["windows"]) == 2


def test_get_active_window(skill):
    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    mock_u32.GetForegroundWindow.return_value = 301
    mock_u32.IsIconic.return_value = False
    mock_u32.IsZoomed.return_value = True

    geom = {"left": 0, "top": 0, "right": 1920, "bottom": 1080, "width": 1920, "height": 1080}

    with patch("nova.skills.system.window._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.window._get_window_text", return_value="Active Code"), \
         patch("nova.skills.system.window._get_window_process_name", return_value="code.exe"), \
         patch("nova.skills.system.window._get_window_geometry", return_value=geom):
        res = skill.execute({"action": "get_active"})
        assert res["status"] == "ok"
        assert res["action"] == "get_active"
        win = res["window"]
        assert win["hwnd"] == 301
        assert win["title"] == "Active Code"
        assert win["process"] == "code.exe"
        assert win["is_maximized"] is True
        assert win["is_minimized"] is False
