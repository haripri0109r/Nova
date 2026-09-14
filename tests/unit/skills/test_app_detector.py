"""
Unit tests for User Application Detector (app_detector.py).

Verifies:
1. Zero user applications (ready: True, open_applications: [])
2. One user application detected
3. Multiple user applications detected
4. Duplicate windows of the same application are deduplicated
5. Windows/system infrastructure processes are ignored (dwm, SearchHost, svchost, etc.)
6. Explorer desktop shell is ignored while folder windows are recognized
7. Nova's own process is excluded
8. Human-readable name resolution (known processes and clean unknown fallback)
9. Message formatting (1 app, 2 apps, 3 apps, 4 apps, >4 apps with Oxford comma)
10. Detector performs no process mutations (no taskkill, no terminate)
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch
import pytest

from nova.skills.system.app_detector import (
    check_shutdown_precondition,
    format_initial_blocked_message,
    format_open_applications_list,
    format_still_open_message,
    get_open_user_applications,
    _is_user_application,
    _resolve_app_display_name,
)


def test_zero_user_applications():
    """Verify check_shutdown_precondition returns ready: True when no windows exist."""
    with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=[]):
        res = check_shutdown_precondition()
        assert res["ready"] is True
        assert res["open_applications"] == []
        assert res["windows"] == []


def test_one_user_application():
    """Verify single open user application is detected and formatted."""
    windows = [
        {"hwnd": 100, "title": "Untitled - Notepad", "process": "notepad.exe", "is_minimized": False, "is_maximized": False},
    ]
    with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
        res = check_shutdown_precondition()
        assert res["ready"] is False
        assert res["open_applications"] == ["Notepad"]
        assert len(res["windows"]) == 1
        assert res["windows"][0]["app_name"] == "Notepad"


def test_multiple_user_applications():
    """Verify multiple distinct user applications are detected."""
    windows = [
        {"hwnd": 101, "title": "Google Chrome", "process": "chrome.exe", "is_minimized": False, "is_maximized": True},
        {"hwnd": 102, "title": "index.ts - Visual Studio Code", "process": "Code.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 103, "title": "Spotify Free", "process": "Spotify.exe", "is_minimized": True, "is_maximized": False},
    ]
    with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
        res = check_shutdown_precondition()
        assert res["ready"] is False
        assert res["open_applications"] == ["Google Chrome", "Visual Studio Code", "Spotify"]
        assert len(res["windows"]) == 3


def test_deduplicate_multiple_windows_same_application():
    """Verify multiple windows from the same application appear only once in open_applications."""
    windows = [
        {"hwnd": 201, "title": "GitHub - Google Chrome", "process": "chrome.exe", "is_minimized": False, "is_maximized": True},
        {"hwnd": 202, "title": "Docs - Google Chrome", "process": "chrome.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 203, "title": "Settings - Google Chrome", "process": "chrome.exe", "is_minimized": True, "is_maximized": False},
        {"hwnd": 204, "title": "file1.py - Code", "process": "Code.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 205, "title": "file2.py - Code", "process": "Code.exe", "is_minimized": False, "is_maximized": False},
    ]
    with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
        res = check_shutdown_precondition()
        assert res["ready"] is False
        assert res["open_applications"] == ["Google Chrome", "Visual Studio Code"]
        assert len(res["windows"]) == 5


def test_ignore_system_windows():
    """Verify system infrastructure processes and background hosts are ignored."""
    windows = [
        {"hwnd": 301, "title": "Desktop Window Manager", "process": "dwm.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 302, "title": "Search", "process": "SearchHost.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 303, "title": "Start", "process": "StartMenuExperienceHost.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 304, "title": "Windows Shell Experience Host", "process": "ShellExperienceHost.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 305, "title": "Settings", "process": "SystemSettings.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 306, "title": "Host Process for Windows Tasks", "process": "taskhostw.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 307, "title": "Service Host", "process": "svchost.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 308, "title": "Program Manager", "process": "explorer.exe", "is_minimized": False, "is_maximized": False},
    ]
    with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
        res = check_shutdown_precondition()
        assert res["ready"] is True
        assert res["open_applications"] == []


def test_explorer_shell_vs_open_folder():
    """Verify Explorer shell is ignored, but user-opened folder windows are counted."""
    windows = [
        {"hwnd": 401, "title": "Program Manager", "process": "explorer.exe", "is_minimized": False, "is_maximized": False},
        {"hwnd": 402, "title": "Documents", "process": "explorer.exe", "is_minimized": False, "is_maximized": False},
    ]
    with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
        res = check_shutdown_precondition()
        assert res["ready"] is False
        assert res["open_applications"] == ["File Explorer"]
        assert len(res["windows"]) == 1


def test_ignore_nova_itself():
    """Verify Nova's own PID or process is excluded from user applications."""
    current_pid = os.getpid()

    mock_u32 = MagicMock()
    mock_u32.IsWindow.return_value = True
    def mock_get_thread_pid(hwnd, pid_ref):
        pid_ref._obj.value = current_pid
        return 1
    mock_u32.GetWindowThreadProcessId.side_effect = mock_get_thread_pid

    windows = [
        {"hwnd": 501, "title": "Nova Assistant", "process": "python.exe", "is_minimized": False, "is_maximized": False},
    ]
    with patch("nova.skills.system.app_detector._get_user32", return_value=mock_u32), \
         patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
        res = check_shutdown_precondition()
        assert res["ready"] is True
        assert res["open_applications"] == []


def test_human_readable_name_resolution():
    """Verify known executables resolve to friendly names, and unknown ones have clean fallbacks."""
    assert _resolve_app_display_name("chrome.exe", "Google Chrome") == "Google Chrome"
    assert _resolve_app_display_name("Code.exe", "Visual Studio Code") == "Visual Studio Code"
    assert _resolve_app_display_name("spotify.exe", "Spotify") == "Spotify"
    assert _resolve_app_display_name("notepad.exe", "Notepad") == "Notepad"
    assert _resolve_app_display_name("msedge.exe", "Edge") == "Microsoft Edge"
    assert _resolve_app_display_name("discord.exe", "Discord") == "Discord"
    assert _resolve_app_display_name("slack.exe", "Slack") == "Slack"
    assert _resolve_app_display_name("windowsterminal.exe", "Terminal") == "Windows Terminal"

    # Unknown executable fallback
    assert _resolve_app_display_name("custom_tool.exe", "Tool Title") == "Custom Tool"
    assert _resolve_app_display_name("my-editor.exe", "Editor") == "My Editor"
    assert _resolve_app_display_name("simple.exe", "") == "Simple"


def test_formatting_helpers():
    """Verify natural English list and message formatting."""
    # 1 app
    assert format_open_applications_list(["Chrome"]) == "Chrome"
    assert format_initial_blocked_message(["Chrome"]) == "Chrome is still open. Please close it and tell me when you're ready."
    assert format_still_open_message(["Chrome"]) == "Chrome is still open. Please close it before I shut down."

    # 2 apps
    assert format_open_applications_list(["Chrome", "VS Code"]) == "Chrome and VS Code"
    assert format_initial_blocked_message(["Chrome", "VS Code"]) == "Chrome and VS Code are still open. Please close them and tell me when you're ready."

    # 3 apps
    assert format_open_applications_list(["Chrome", "VS Code", "Spotify"]) == "Chrome, VS Code, and Spotify"

    # 4 apps
    apps4 = ["Chrome", "VS Code", "Spotify", "Notepad"]
    assert format_open_applications_list(apps4) == "Chrome, VS Code, Spotify, and Notepad"
    assert format_initial_blocked_message(apps4) == "Chrome, VS Code, Spotify, and Notepad are still open. Please close them and tell me when you're ready."

    # > 4 apps
    apps6 = ["Chrome", "VS Code", "Spotify", "Notepad", "Discord", "Slack"]
    assert format_open_applications_list(apps6) == "Chrome, VS Code, Spotify, Notepad, and 2 other applications"

    apps5 = ["Chrome", "VS Code", "Spotify", "Notepad", "Discord"]
    assert format_open_applications_list(apps5) == "Chrome, VS Code, Spotify, Notepad, and 1 other application"


def test_detector_is_purely_read_only():
    """Verify app_detector does not call subprocess or modify any state."""
    with patch("subprocess.run") as mock_subproc, patch("os.system") as mock_system:
        windows = [
            {"hwnd": 601, "title": "Notepad", "process": "notepad.exe", "is_minimized": False, "is_maximized": False},
        ]
        with patch("nova.skills.system.app_detector._enumerate_top_level_windows", return_value=windows):
            res = check_shutdown_precondition()
            assert res["ready"] is False
            assert res["open_applications"] == ["Notepad"]

        mock_subproc.assert_not_called()
        mock_system.assert_not_called()
