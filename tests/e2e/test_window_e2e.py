"""
Real Windows End-to-End Test Suite for Phase 5.8-E.

Verifies real Windows execution of WindowSkill on actual native Windows applications:
1. Lifecycle of a real harmless native test window (notepad.exe):
   - Launch Notepad process
   - Discover its actual window via WindowSkill.execute({"action": "list"})
   - Focus Notepad (verifies foreground or honest UIPI restricted result)
   - Maximize Notepad (verifies IsZoomed == True)
   - Snap Notepad to the left (verifies monitor work area geometry)
   - Minimize Notepad (verifies IsIconic == True)
   - Restore Notepad (verifies normal floating non-iconic non-zoomed state)
   - Gracefully close Notepad using WM_CLOSE (verifies window is destroyed)
   - Guaranteed cleanup in try/finally
2. Real Windows desktop query operations:
   - list open windows
   - get active window
3. End-to-end pipeline:
   User Text -> Brain -> Deterministic Fast Path -> WindowSkill -> Real Windows API verification
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
import time
import pytest

from nova.brain.engine import BrainEngine
from nova.brain.models import RecognizedInput
from nova.brain.planner import get_planner
from nova.brain.types import IntentCategory
from nova.skills.registry import registry
from nova.skills.system.window import WindowSkill


@pytest.fixture
def window_skill() -> WindowSkill:
    return WindowSkill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_notepad_lifecycle(window_skill: WindowSkill):
    """
    Exercise the full lifecycle of a real Windows application window (notepad.exe):
    launch -> discover -> focus -> maximize -> snap left -> minimize -> restore -> close.
    """
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(1.0)
    u32 = ctypes.windll.user32

    try:
        # 1. Discover Notepad window
        list_res = window_skill.execute({"action": "list"})
        assert list_res["status"] == "ok"
        windows = list_res.get("windows", [])
        notepad_windows = [w for w in windows if "notepad" in w["process"].lower()]
        assert len(notepad_windows) >= 1, f"Expected Notepad in list, got: {windows}"

        hwnd = notepad_windows[0]["hwnd"]
        assert hwnd > 0
        assert u32.IsWindow(hwnd)

        # 2. Focus Notepad (honest verification: ok if focused, restricted if background session blocked)
        focus_res = window_skill.execute({"action": "focus", "target": "notepad"})
        assert focus_res["status"] in ("ok", "restricted")
        assert focus_res["hwnd"] == hwnd

        # 3. Maximize Notepad
        max_res = window_skill.execute({"action": "maximize", "target": "notepad"})
        assert max_res["status"] == "ok"
        assert max_res["is_maximized"] is True
        assert bool(u32.IsZoomed(hwnd)) is True

        # 4. Snap Notepad to the left
        snap_res = window_skill.execute({"action": "snap", "position": "left", "target": "notepad"})
        assert snap_res["status"] == "ok"
        assert snap_res["position"] == "left"
        geom = snap_res.get("geometry")
        target_geom = snap_res.get("target_geometry")
        assert geom is not None
        assert target_geom is not None
        # Verify snapped geometry within 15px tolerance
        assert abs(geom["left"] - target_geom["x"]) <= 15
        assert abs(geom["width"] - target_geom["width"]) <= 15

        # 5. Minimize Notepad
        min_res = window_skill.execute({"action": "minimize", "target": "notepad"})
        assert min_res["status"] == "ok"
        assert min_res["is_minimized"] is True
        assert bool(u32.IsIconic(hwnd)) is True

        # 6. Restore Notepad to normal floating state
        res_res = window_skill.execute({"action": "restore", "target": "notepad"})
        assert res_res["status"] == "ok"
        assert res_res["is_minimized"] is False
        assert res_res["is_maximized"] is False
        assert bool(u32.IsIconic(hwnd)) is False
        assert bool(u32.IsZoomed(hwnd)) is False

        # 7. Close Notepad gracefully via WM_CLOSE
        close_res = window_skill.execute({"action": "close", "target": "notepad"})
        assert close_res["status"] == "ok"
        # Verify window is no longer a valid window
        assert not u32.IsWindow(hwnd)

    finally:
        # Clean up process if still running
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=2.0)
        except Exception:
            pass


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_list_and_get_active(window_skill: WindowSkill):
    """Test real query operations on Windows desktop without modifying window state."""
    # List top-level windows
    list_res = window_skill.execute({"action": "list"})
    assert list_res["status"] == "ok"
    assert "count" in list_res
    assert isinstance(list_res["windows"], list)

    # Get active window
    active_res = window_skill.execute({"action": "get_active"})
    assert active_res["status"] == "ok"
    assert active_res["action"] == "get_active"
    # window is either None (in headless session) or a dict with details
    win = active_res.get("window")
    if win is not None:
        assert "hwnd" in win
        assert "title" in win
        assert "process" in win


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
@pytest.mark.asyncio
async def test_real_windows_pipeline_execution():
    """
    Test the complete Nova pipeline for window management:
    Natural text -> Brain -> Intent Classifier -> Planner -> WindowSkill execution -> Real Windows.
    """
    proc = subprocess.Popen(["notepad.exe"])
    time.sleep(1.0)
    u32 = ctypes.windll.user32

    try:
        engine = BrainEngine()
        await engine.initialize()
        planner = get_planner()
        await planner.initialize()

        # Step 1: "maximize Notepad"
        cmd = "maximize Notepad"
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.WINDOW
        assert intent.entities.get("action") == "maximize"

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.tool == "window"

        skill = registry.get(step.tool)
        assert skill is not None
        result = skill.execute(step.parameters)
        assert result["status"] == "ok"
        assert result["is_maximized"] is True
        hwnd = result["hwnd"]
        assert bool(u32.IsZoomed(hwnd)) is True

        # Step 2: "minimize Notepad"
        cmd_min = "minimize Notepad"
        intent_min = await engine._intent_classifier.classify(RecognizedInput(text=cmd_min))
        plan_min = await planner.plan(cmd_min, intent_min)
        result_min = skill.execute(plan_min.steps[0].parameters)
        assert result_min["status"] == "ok"
        assert result_min["is_minimized"] is True
        assert bool(u32.IsIconic(hwnd)) is True

        # Step 3: "close Notepad window"
        cmd_close = "close Notepad window"
        intent_close = await engine._intent_classifier.classify(RecognizedInput(text=cmd_close))
        assert intent_close.category == IntentCategory.WINDOW
        assert intent_close.entities.get("action") == "close"

        plan_close = await planner.plan(cmd_close, intent_close)
        result_close = skill.execute(plan_close.steps[0].parameters)
        assert result_close["status"] == "ok"
        assert not u32.IsWindow(hwnd)

    finally:
        try:
            if proc.poll() is None:
                proc.terminate()
                proc.wait(timeout=2.0)
        except Exception:
            pass
