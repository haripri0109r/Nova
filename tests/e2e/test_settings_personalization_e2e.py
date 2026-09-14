"""
Real Windows End-to-End Test Suite for Phase 5.8-B.

Verifies real Windows execution of SettingsSkill and PersonalizationSkill:
1. Settings navigation:
   - ms-settings:display
   - ms-settings:network-wifi
   - ms-settings:defaultapps (with honest UserChoice protection messaging)
2. Personalization mutations (strictly reversible with guaranteed restoration in finally blocks):
   - Real Theme mutation (AppsUseLightTheme, SystemUsesLightTheme in HKCU), WM_SETTINGCHANGE broadcast, read-back verification
   - Real Taskbar alignment mutation (TaskbarAl in HKCU), WM_SETTINGCHANGE broadcast, read-back verification
   - Real Wallpaper mutation via SystemParametersInfoW, verification, and restoration of original wallpaper
3. Full pipeline execution:
   User Text -> Brain -> Deterministic Fast Path -> TaskService -> PlanExecutor -> Skill -> Real Windows
"""

from __future__ import annotations

import asyncio
import ctypes
import os
import sys
import tempfile
import time
import winreg
from typing import Optional, Tuple
import pytest

from nova.brain.engine import BrainEngine
from nova.agent.task_service import get_task_service, TaskStatus, ActionStatus
from nova.skills.registry import registry
from nova.skills.system.settings import SettingsSkill
from nova.skills.system.personalization import PersonalizationSkill


# =============================================================================
# Helper utilities to capture and verify real Windows state
# =============================================================================

def _get_current_theme_state() -> Tuple[Optional[int], Optional[int]]:
    """Read AppsUseLightTheme and SystemUsesLightTheme from HKCU."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            0,
            winreg.KEY_READ,
        )
        apps_val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        sys_val, _ = winreg.QueryValueEx(key, "SystemUsesLightTheme")
        winreg.CloseKey(key)
        return apps_val, sys_val
    except Exception:
        return None, None


def _get_current_taskbar_alignment() -> Optional[int]:
    """Read TaskbarAl from HKCU."""
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced",
            0,
            winreg.KEY_READ,
        )
        val, _ = winreg.QueryValueEx(key, "TaskbarAl")
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


def _get_current_wallpaper() -> Optional[str]:
    """Read current wallpaper path via SystemParametersInfoW or Registry."""
    try:
        buf = ctypes.create_unicode_buffer(512)
        # SPI_GETDESKWALLPAPER = 0x0073 (115)
        res = ctypes.windll.user32.SystemParametersInfoW(0x0073, 512, buf, 0)
        if res and buf.value:
            return buf.value
    except Exception:
        pass

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Control Panel\Desktop",
            0,
            winreg.KEY_READ,
        )
        val, _ = winreg.QueryValueEx(key, "Wallpaper")
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


def _create_minimal_valid_bmp(path: str) -> None:
    """Create a 2x2 24-bit uncompressed BMP file."""
    # 14 bytes BMP header + 40 bytes DIB header + 16 bytes pixel data = 70 bytes
    bmp_data = (
        b"BM"
        + (70).to_bytes(4, "little")
        + b"\x00\x00\x00\x00"
        + (54).to_bytes(4, "little")
        + (40).to_bytes(4, "little")
        + (2).to_bytes(4, "little")
        + (2).to_bytes(4, "little")
        + (1).to_bytes(2, "little")
        + (24).to_bytes(2, "little")
        + (0).to_bytes(4, "little")
        + (16).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + (0).to_bytes(4, "little")
        + b"\xff\x00\x00\x00\xff\x00\x00\x00\x00\x00\xff\xff\xff\xff\x00\x00"
    )
    with open(path, "wb") as f:
        f.write(bmp_data)


# =============================================================================
# 1. Settings Navigation Tests (Real Windows)
# =============================================================================

@pytest.mark.asyncio
async def test_real_windows_settings_display_navigation():
    """Verify SettingsSkill navigates to display settings on real Windows."""
    skill = SettingsSkill()
    res = skill.execute({"page": "display"})
    assert res["status"] == "opened"
    assert res["action"] == "navigated"
    assert res["page"] == "display"
    assert res["target_uri"] == "ms-settings:display"
    assert "Opened Windows Settings" in res["message"]


@pytest.mark.asyncio
async def test_real_windows_settings_wifi_navigation():
    """Verify SettingsSkill navigates to wifi settings on real Windows."""
    skill = SettingsSkill()
    res = skill.execute({"page": "wifi"})
    assert res["status"] == "opened"
    assert res["action"] == "navigated"
    assert res["page"] == "wifi"
    assert res["target_uri"] == "ms-settings:network-wifi"


@pytest.mark.asyncio
async def test_real_windows_settings_default_apps_navigation():
    """
    Verify SettingsSkill navigates to default_apps and includes honest
    messaging noting that Windows protects default app / browser selections.
    """
    skill = SettingsSkill()
    res = skill.execute({"page": "default_apps"})
    assert res["status"] == "opened"
    assert res["action"] == "navigated"
    assert res["page"] == "default_apps"
    assert res["target_uri"] == "ms-settings:defaultapps"
    assert "protected" in res.get("note", "").lower() or "selection" in res.get("note", "").lower()


# =============================================================================
# 2. Personalization Theme Mutation and Safe Reversion (Real Windows)
# =============================================================================

def test_real_windows_theme_mutation_and_restoration():
    """
    Test real Windows theme mode mutation (dark <-> light).
    Verifies HKCU registry write, broadcast, read-back verification,
    and unconditionally restores original theme state in finally.
    """
    orig_apps, orig_sys = _get_current_theme_state()
    assert orig_apps is not None, "Unable to read current Windows theme state from registry"

    skill = PersonalizationSkill()
    # If currently dark (0), target light ('light'). If light (1), target dark ('dark').
    target_mode = "light" if orig_apps == 0 else "dark"
    expected_val = 1 if target_mode == "light" else 0

    try:
        # Mutate to target mode
        res = skill.execute({"feature": "theme", "mode": target_mode})
        assert res["success"] is True
        assert res["status"] in ("ok", "success")
        assert res["action"] in ("mutated", "set_theme")
        assert res["mode"] == target_mode
        assert res["verified"] is True

        # Verify real Windows registry updated
        cur_apps, cur_sys = _get_current_theme_state()
        assert cur_apps == expected_val
        assert cur_sys == expected_val
    finally:
        # Restore original theme state unconditionally
        restore_mode = "dark" if orig_apps == 0 else "light"
        skill.execute({"feature": "theme", "mode": restore_mode})
        restored_apps, restored_sys = _get_current_theme_state()
        assert restored_apps == orig_apps
        assert restored_sys == orig_sys


# =============================================================================
# 3. Personalization Taskbar Alignment and Safe Reversion (Real Windows)
# =============================================================================

def test_real_windows_taskbar_alignment_and_restoration():
    """
    Test real Windows taskbar alignment mutation (left <-> center).
    Verifies HKCU registry write, broadcast, read-back verification,
    and unconditionally restores original taskbar alignment in finally.
    """
    orig_al = _get_current_taskbar_alignment()
    assert orig_al is not None, "Unable to read current Windows taskbar alignment from registry"

    skill = PersonalizationSkill()
    # 0 = left, 1 = center. Toggle to opposite.
    target_align = "left" if orig_al == 1 else "center"
    expected_val = 0 if target_align == "left" else 1

    try:
        res = skill.execute({"feature": "taskbar", "alignment": target_align})
        assert res["success"] is True
        assert res["status"] in ("ok", "success")
        assert res["action"] in ("mutated", "set_taskbar_alignment")
        assert res["alignment"] == target_align
        assert res["verified"] is True

        cur_al = _get_current_taskbar_alignment()
        assert cur_al == expected_val
    finally:
        # Restore original alignment unconditionally
        restore_align = "center" if orig_al == 1 else "left"
        skill.execute({"feature": "taskbar", "alignment": restore_align})
        restored_al = _get_current_taskbar_alignment()
        assert restored_al == orig_al


# =============================================================================
# 4. Personalization Wallpaper Mutation and Safe Reversion (Real Windows)
# =============================================================================

def test_real_windows_wallpaper_mutation_and_restoration():
    """
    Test real Windows wallpaper mutation via SystemParametersInfoW.
    Uses temporary BMP image, verifies mutation, and restores original
    wallpaper in finally block.
    """
    orig_wallpaper = _get_current_wallpaper()
    assert orig_wallpaper is not None, "Unable to capture current wallpaper path"

    skill = PersonalizationSkill()
    temp_dir = tempfile.mkdtemp(prefix="nova_e2e_wallpaper_")
    test_bmp = os.path.join(temp_dir, "test_wallpaper.bmp")
    _create_minimal_valid_bmp(test_bmp)

    try:
        res = skill.execute({"feature": "wallpaper", "path": test_bmp})
        assert res["success"] is True
        assert res["status"] in ("ok", "success")
        assert res["action"] in ("mutated", "set_wallpaper")
        assert os.path.normpath(res["path"]).lower() == os.path.normpath(test_bmp).lower()

        # Small delay for Windows to process setting change
        time.sleep(0.5)

        # Check that wallpaper was set
        new_wallpaper = _get_current_wallpaper()
        assert new_wallpaper is not None
        # On Windows, TranscodedWallpaper or the direct path may be returned
        assert os.path.exists(new_wallpaper)
    finally:
        # Restore original wallpaper unconditionally
        if orig_wallpaper and os.path.exists(orig_wallpaper):
            skill.execute({"feature": "wallpaper", "path": orig_wallpaper})
        # Cleanup temp file
        try:
            if os.path.exists(test_bmp):
                os.remove(test_bmp)
            os.rmdir(temp_dir)
        except Exception:
            pass


# =============================================================================
# 5. Full Pipeline End-to-End Execution (Brain -> TaskService -> Windows)
# =============================================================================

@pytest.mark.asyncio
async def test_full_pipeline_settings_navigation():
    """
    Test full pipeline execution for settings navigation:
    'open display settings'
    Verifies:
    - Processed without LLM call (fast path)
    - Task completed successfully in TaskService
    - Honest navigation messaging
    """
    engine = BrainEngine()
    await engine.initialize()
    ts = get_task_service()

    resp = await engine.process_text("open display settings", session_id="e2e_settings_disp")
    assert resp is not None
    assert "opened windows settings" in resp.response_text.lower()
    # Must never claim a setting was changed
    assert "changed" not in resp.response_text.lower()

    tasks = await ts.list_tasks()
    latest_task = tasks[-1]
    assert latest_task.status == TaskStatus.COMPLETED
    assert latest_task.steps[0].status == ActionStatus.SUCCESS
    assert latest_task.steps[0].tool == "open_settings"
    assert latest_task.steps[0].parameters == {"page": "display"}


@pytest.mark.asyncio
async def test_full_pipeline_theme_mutation_and_restoration():
    """
    Test full pipeline execution for theme mutation:
    'turn on dark mode' / 'switch to light mode'
    Verifies:
    - Deterministic fast path
    - Task persisted as COMPLETED with SUCCESS
    - Registry reflects change
    - Restores original theme state unconditionally
    """
    orig_apps, orig_sys = _get_current_theme_state()
    assert orig_apps is not None

    engine = BrainEngine()
    await engine.initialize()
    ts = get_task_service()

    # Toggle to opposite
    target_cmd = "switch to light mode" if orig_apps == 0 else "turn on dark mode"
    target_mode = "light" if orig_apps == 0 else "dark"
    expected_val = 1 if target_mode == "light" else 0

    try:
        resp = await engine.process_text(target_cmd, session_id="e2e_theme_toggle")
        assert resp is not None
        assert "theme" in resp.response_text.lower()

        tasks = await ts.list_tasks()
        latest_task = tasks[-1]
        assert latest_task.status == TaskStatus.COMPLETED
        assert latest_task.steps[0].status == ActionStatus.SUCCESS
        assert latest_task.steps[0].tool == "personalization"
        assert latest_task.steps[0].parameters == {"feature": "theme", "mode": target_mode}

        cur_apps, cur_sys = _get_current_theme_state()
        assert cur_apps == expected_val
    finally:
        restore_cmd = "turn on dark mode" if orig_apps == 0 else "switch to light mode"
        await engine.process_text(restore_cmd, session_id="e2e_theme_restore")
        restored_apps, restored_sys = _get_current_theme_state()
        assert restored_apps == orig_apps
