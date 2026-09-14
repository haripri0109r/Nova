"""
Real Windows End-to-End Test Suite for Phase 5.8-C.

Verifies real Windows execution of DisplaySkill and AudioSkill:
1. Real Windows Display capabilities:
   - get_display_info (monitors count, primary display width, height, refresh rate, orientation)
   - get_resolution, get_refresh_rate, get_orientation
   - Resolution validation rejection for unsupported video modes
   - CDS_TEST pre-validation on actual display driver (honest restriction if rejected)
   - Reversible brightness control via WMI (with read-back verification and restoration in finally)
   - Night Light honest restriction (status='restricted', ms-settings:nightlight navigation)
2. Real Windows Audio capabilities:
   - Master volume read, small reversible delta, and read-back verification (restored in finally)
   - Master mute toggle, verification, and restoration in finally
   - Output device enumeration (eRender / active speakers/headphones)
   - Input device enumeration (eCapture / active microphones)
   - Microphone status (volume, mute state)
   - Default audio output device resolution and honest restriction (ms-settings:sound navigation)
3. Full pipeline execution:
   User Text -> Brain -> Deterministic Fast Path -> TaskService -> PlanExecutor -> Real Windows
"""

from __future__ import annotations

import asyncio
import os
import sys
import pytest

from nova.brain.engine import BrainEngine
from nova.agent.task_service import get_task_service, TaskStatus, ActionStatus
from nova.skills.registry import registry
from nova.skills.system.display import DisplaySkill
from nova.skills.system.audio import AudioSkill


@pytest.fixture
def display_skill() -> DisplaySkill:
    return DisplaySkill()


@pytest.fixture
def audio_skill() -> AudioSkill:
    return AudioSkill()


# =============================================================================
# 1. Real Windows Display Query & Validation Tests
# =============================================================================


def test_real_windows_display_info(display_skill: DisplaySkill):
    """Query real Windows display topology via EnumDisplayDevicesW and EnumDisplaySettingsW."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = display_skill.execute({"action": "get_display_info"})
    assert res["status"] == "ok"
    assert res["monitor_count"] >= 1
    assert "primary_display" in res

    primary = res["primary_display"]
    assert primary["width"] > 0
    assert primary["height"] > 0
    assert primary["refresh_rate"] > 0
    assert primary["orientation"] in ("landscape", "portrait", "landscape_flipped", "portrait_flipped")
    assert primary["bits_per_pixel"] in (16, 24, 32)


def test_real_windows_resolution_and_refresh_read(display_skill: DisplaySkill):
    """Query individual display metrics on real Windows."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res_res = display_skill.execute({"action": "get_resolution"})
    assert res_res["status"] == "ok"
    assert res_res["width"] > 0
    assert res_res["height"] > 0

    rate_res = display_skill.execute({"action": "get_refresh_rate"})
    assert rate_res["status"] == "ok"
    assert rate_res["refresh_rate"] > 0

    orient_res = display_skill.execute({"action": "get_orientation"})
    assert orient_res["status"] == "ok"
    assert orient_res["orientation"] in ("landscape", "portrait", "landscape_flipped", "portrait_flipped")


def test_real_windows_resolution_validation_rejection(display_skill: DisplaySkill):
    """Attempting an unsupported resolution combination must be rejected without changing display."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    initial = display_skill.execute({"action": "get_resolution"})
    assert initial["status"] == "ok"

    res = display_skill.execute({"action": "set_resolution", "width": 1234, "height": 567})
    assert res["status"] == "unsupported"
    assert "not supported" in res["message"].lower()

    # Verify mode did not change
    after = display_skill.execute({"action": "get_resolution"})
    assert after["width"] == initial["width"]
    assert after["height"] == initial["height"]


def test_real_windows_display_mode_cds_test_safety(display_skill: DisplaySkill):
    """
    Test CDS_TEST pre-validation on actual display driver.
    On modern laptop hybrid graphics, ChangeDisplaySettingsExW direct mode changes
    are often rejected by the driver (CDS_TEST returns -1).
    Nova must safely catch this, navigate to Settings, and never leave display broken.
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    initial = display_skill.execute({"action": "get_display_info"})
    assert initial["status"] == "ok"
    current_w = initial["primary_display"]["width"]
    current_h = initial["primary_display"]["height"]

    # Re-apply current resolution via CDS_TEST verification
    res = display_skill.execute({"action": "set_resolution", "width": current_w, "height": current_h})
    assert res["status"] in ("ok", "restricted")

    # Read back to ensure system remains stable
    after = display_skill.execute({"action": "get_resolution"})
    assert after["status"] == "ok"
    assert after["width"] == current_w
    assert after["height"] == current_h


def test_real_windows_brightness_control_reversible(display_skill: DisplaySkill):
    """
    Query real Windows brightness. If supported via WMI, test a small reversible change
    and guarantee restoration inside finally. If hardware is unsupported (external monitor),
    verify honest status='unsupported'.
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    read_res = display_skill.execute({"action": "get_brightness"})
    if read_res["status"] == "unsupported":
        # External desktop monitor or virtual display without WmiMonitorBrightness
        assert "not available" in read_res["message"].lower() or "external" in read_res["message"].lower()
        return

    assert read_res["status"] == "ok"
    orig_brightness = read_res["brightness"]
    assert 0 <= orig_brightness <= 100

    try:
        # Small delta (+5 or -5)
        test_level = orig_brightness - 5 if orig_brightness >= 50 else orig_brightness + 5
        set_res = display_skill.execute({"action": "set_brightness", "level": test_level})
        assert set_res["status"] == "ok"
        assert set_res["brightness"] == test_level

        # Read back to confirm
        verify_res = display_skill.execute({"action": "get_brightness"})
        assert verify_res["status"] == "ok"
        assert verify_res["brightness"] == test_level
    finally:
        # Guaranteed restoration
        display_skill.execute({"action": "set_brightness", "level": orig_brightness})
        final_read = display_skill.execute({"action": "get_brightness"})
        assert final_read["brightness"] == orig_brightness


def test_real_windows_night_light_honest_restriction(display_skill: DisplaySkill):
    """Night light must honestly report restriction and navigate to ms-settings:nightlight."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = display_skill.execute({"action": "night_light"})
    assert res["status"] == "restricted"
    assert res["action"] == "navigated"
    assert res["target_uri"] == "ms-settings:nightlight"
    assert "restricts" in res["message"].lower() or "cloudstore" in res["message"].lower()


# =============================================================================
# 2. Real Windows Audio Capabilities & Device Resolution Tests
# =============================================================================


def test_real_windows_master_volume_read_and_delta_reversible(audio_skill: AudioSkill):
    """
    Read real Windows master volume, apply a small delta, verify read-back,
    and guarantee exact restoration in finally.
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    initial = audio_skill.execute({"action": "get_volume"})
    assert initial["status"] == "ok"
    orig_vol = initial["volume"]
    assert 0 <= orig_vol <= 100

    try:
        # Apply small delta of 2%
        test_target = orig_vol - 2 if orig_vol >= 50 else orig_vol + 2
        set_res = audio_skill.execute({"action": "set_volume", "level": test_target})
        assert set_res["status"] == "ok"
        assert set_res["volume"] == test_target
        assert set_res["verified"] is True

        # Read back independently
        verify_res = audio_skill.execute({"action": "get_volume"})
        assert verify_res["status"] == "ok"
        assert verify_res["volume"] == test_target
    finally:
        # Guaranteed restoration of master volume
        audio_skill.execute({"action": "set_volume", "level": orig_vol})
        restored = audio_skill.execute({"action": "get_volume"})
        assert restored["volume"] == orig_vol


def test_real_windows_master_mute_toggle_reversible(audio_skill: AudioSkill):
    """
    Read mute state, toggle mute, verify read-back, and guarantee restoration in finally.
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    initial = audio_skill.execute({"action": "get_volume"})
    assert initial["status"] == "ok"
    orig_muted = initial["muted"]

    try:
        # Toggle mute
        target_action = "unmute" if orig_muted else "mute"
        res = audio_skill.execute({"action": target_action})
        assert res["status"] == "ok"
        assert res["muted"] != orig_muted

        verify_res = audio_skill.execute({"action": "get_volume"})
        assert verify_res["muted"] != orig_muted
    finally:
        # Guaranteed restoration
        restore_action = "mute" if orig_muted else "unmute"
        audio_skill.execute({"action": restore_action})
        final_read = audio_skill.execute({"action": "get_volume"})
        assert final_read["muted"] == orig_muted


def test_real_windows_output_devices_enumeration(audio_skill: AudioSkill):
    """Enumerate active render devices on real Windows."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = audio_skill.execute({"action": "list_outputs"})
    assert res["status"] == "ok"
    assert res["count"] >= 1
    assert len(res["devices"]) >= 1
    for dev in res["devices"]:
        assert "name" in dev
        assert len(dev["name"]) > 0


def test_real_windows_input_devices_enumeration(audio_skill: AudioSkill):
    """Enumerate active capture devices (microphones) on real Windows."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = audio_skill.execute({"action": "list_inputs"})
    assert res["status"] == "ok"
    assert isinstance(res["devices"], list)


def test_real_windows_microphone_status(audio_skill: AudioSkill):
    """Query microphone status via Core Audio on real Windows."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = audio_skill.execute({"action": "get_mic_status"})
    assert res["status"] in ("ok", "error", "unsupported")
    if res["status"] == "ok":
        assert 0 <= res["volume"] <= 100
        assert isinstance(res["muted"], bool)


def test_real_windows_default_audio_device_switching_restriction(audio_skill: AudioSkill):
    """
    Test setting default output device against an enumerated device:
    Resolves device deterministically, verifies device exists, acknowledges
    Windows restriction on background endpoint switching, and navigates to ms-settings:sound.
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    list_res = audio_skill.execute({"action": "list_outputs"})
    assert list_res["status"] == "ok"
    assert len(list_res["devices"]) >= 1

    first_device = list_res["devices"][0]["name"]
    res = audio_skill.execute({"action": "set_default_output", "device_name": first_device})
    assert res["status"] == "restricted"
    assert res["action"] == "navigated"
    assert res["target_uri"] == "ms-settings:sound"
    assert "restricts" in res["message"].lower()


# =============================================================================
# 3. Full Pipeline Execution Tests (Brain -> TaskService -> PlanExecutor)
# =============================================================================


@pytest.mark.asyncio
async def test_full_pipeline_volume_command(audio_skill: AudioSkill):
    """
    Full pipeline test:
    'set volume to 42' -> BrainEngine -> CommandPlanner -> TaskService -> PlanExecutor -> Real Windows
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    initial = audio_skill.execute({"action": "get_volume"})
    orig_vol = initial["volume"]

    try:
        engine = BrainEngine()
        await engine.initialize()
        ts = get_task_service()

        test_target_vol = 38 if orig_vol >= 50 else 42
        user_text = f"set volume to {test_target_vol}"

        resp = await engine.process_text(user_text, session_id="e2e_audio_pipeline")
        assert resp is not None

        tasks = await ts.list_tasks()
        latest_task = tasks[-1]
        assert latest_task.status == TaskStatus.COMPLETED
        assert latest_task.steps[0].status == ActionStatus.SUCCESS

        # Verify real Windows volume was changed to target
        after = audio_skill.execute({"action": "get_volume"})
        assert after["volume"] == test_target_vol
    finally:
        # Guaranteed restoration of master volume
        audio_skill.execute({"action": "set_volume", "level": orig_vol})


@pytest.mark.asyncio
async def test_full_pipeline_display_info_command():
    """
    Full pipeline test:
    'what is my resolution?' -> BrainEngine -> CommandPlanner -> TaskService -> PlanExecutor -> Real Windows
    """
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    engine = BrainEngine()
    await engine.initialize()
    ts = get_task_service()

    resp = await engine.process_text("what is my resolution?", session_id="e2e_display_pipeline")
    assert resp is not None

    tasks = await ts.list_tasks()
    latest_task = tasks[-1]
    assert latest_task.status == TaskStatus.COMPLETED
    assert latest_task.steps[0].status == ActionStatus.SUCCESS
    assert latest_task.steps[0].tool == "display"
