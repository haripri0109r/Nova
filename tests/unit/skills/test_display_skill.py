"""
Unit tests for DisplaySkill (Phase 5.8-C).

Verifies:
- Skill registration in SkillRegistry and alias resolution
- Strict parameter schema validation (additionalProperties: False)
- Brightness read / set / adjust with mock and hardware boundaries
- Display info query (monitor count, resolution, refresh rate, orientation)
- Resolution and refresh rate validation against supported modes
- Orientation validation and CDS_TEST pre-validation
- Honest handling of CDS_TEST failure (status='restricted', ms-settings:display navigation)
- Honest handling of Night Light (status='restricted', ms-settings:nightlight navigation, no fake registry writes)
- Unsupported hardware handling (status='unsupported' when WMI is unavailable)
"""

import sys
from typing import Any, Dict
from unittest.mock import MagicMock, patch

import pytest

from nova.skills.base import BaseSkill
from nova.skills.registry import registry
from nova.skills.system.display import (
    DEVMODEW,
    DISP_CHANGE_BADMODE,
    DISP_CHANGE_FAILED,
    DISP_CHANGE_SUCCESSFUL,
    DisplaySkill,
    _parse_step_amount,
)


@pytest.fixture
def skill() -> DisplaySkill:
    return DisplaySkill()


# ============================================================================
# 1. Registration & Base Interface Tests
# ============================================================================


def test_display_skill_registration(skill: DisplaySkill):
    """DisplaySkill must be registered in SkillRegistry with canonical intent 'display'."""
    retrieved = registry.get("display")
    assert retrieved is not None
    assert isinstance(retrieved, DisplaySkill)
    assert retrieved.intent == "display"
    assert "display" in retrieved.description.lower()


def test_display_skill_alias_resolution():
    """SkillRegistry must resolve 'display_control' alias to 'display'."""
    retrieved = registry.get("display_control")
    assert retrieved is not None
    assert isinstance(retrieved, DisplaySkill)


def test_display_skill_can_handle(skill: DisplaySkill):
    """can_handle must accept display and display_control intents."""
    assert skill.can_handle({"intent": "display"}) is True
    assert skill.can_handle({"intent": "display_control"}) is True
    assert skill.can_handle({"intent": "set_brightness"}) is True
    assert skill.can_handle({"intent": "volume"}) is False


# ============================================================================
# 2. Schema & Parameter Validation Tests
# ============================================================================


def test_display_schema_structure(skill: DisplaySkill):
    """Schema must define additionalProperties: False and require action."""
    schema = skill.parameters_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "action" in schema["required"]
    assert "get_brightness" in schema["properties"]["action"]["enum"]
    assert "set_resolution" in schema["properties"]["action"]["enum"]
    assert "night_light" in schema["properties"]["action"]["enum"]


def test_display_schema_rejects_missing_action(skill: DisplaySkill):
    """Validation must raise ValueError if action is missing."""
    with pytest.raises(ValueError, match="missing required 'action' parameter"):
        skill.validate({})


def test_display_schema_rejects_invalid_action(skill: DisplaySkill):
    """Validation must raise ValueError for unknown action."""
    with pytest.raises(ValueError, match="invalid action"):
        skill.validate({"action": "explode_monitor"})


def test_display_schema_rejects_unexpected_properties(skill: DisplaySkill):
    """Validation must reject extra parameters under additionalProperties: False."""
    with pytest.raises(ValueError, match="Unexpected parameter 'malicious_input'"):
        skill.validate({"action": "get_brightness", "malicious_input": "rm -rf"})


def test_display_schema_validates_set_brightness_level(skill: DisplaySkill):
    """set_brightness requires integer level between 0 and 100."""
    with pytest.raises(ValueError, match="requires 'level' parameter"):
        skill.validate({"action": "set_brightness"})

    with pytest.raises(ValueError, match="'level' must be between 0 and 100"):
        skill.validate({"action": "set_brightness", "level": 150})

    with pytest.raises(ValueError, match="'level' must be between 0 and 100"):
        skill.validate({"action": "set_brightness", "level": -10})

    assert skill.validate({"action": "set_brightness", "level": 75}) is True


def test_display_schema_validates_set_resolution(skill: DisplaySkill):
    """set_resolution requires positive integer width and height."""
    with pytest.raises(ValueError, match="requires both 'width' and 'height'"):
        skill.validate({"action": "set_resolution", "width": 1920})

    with pytest.raises(ValueError, match="must be positive integers"):
        skill.validate({"action": "set_resolution", "width": -1920, "height": 1080})

    assert skill.validate({"action": "set_resolution", "width": 1920, "height": 1080}) is True


def test_display_schema_validates_set_refresh_rate(skill: DisplaySkill):
    """set_refresh_rate requires positive integer refresh_rate."""
    with pytest.raises(ValueError, match="requires 'refresh_rate'"):
        skill.validate({"action": "set_refresh_rate"})

    with pytest.raises(ValueError, match="must be a positive integer"):
        skill.validate({"action": "set_refresh_rate", "refresh_rate": 0})

    assert skill.validate({"action": "set_refresh_rate", "refresh_rate": 144}) is True


def test_display_schema_validates_set_orientation(skill: DisplaySkill):
    """set_orientation requires valid orientation enum."""
    with pytest.raises(ValueError, match="requires 'orientation'"):
        skill.validate({"action": "set_orientation"})

    with pytest.raises(ValueError, match="invalid orientation"):
        skill.validate({"action": "set_orientation", "orientation": "upside_down"})

    assert skill.validate({"action": "set_orientation", "orientation": "portrait"}) is True


# ============================================================================
# 3. Step Amount Parser Tests
# ============================================================================


def test_parse_step_amount():
    assert _parse_step_amount(None, default=10) == 10
    assert _parse_step_amount("small") == 10
    assert _parse_step_amount("medium") == 20
    assert _parse_step_amount("large") == 30
    assert _parse_step_amount(15) == 15
    assert _parse_step_amount("25") == 25
    assert _parse_step_amount("invalid", default=10) == 10


# ============================================================================
# 4. Brightness Unit Tests (Mocked WMI Boundary)
# ============================================================================


def test_get_brightness_success(skill: DisplaySkill):
    """get_brightness returns current brightness from WmiMonitorBrightness."""
    mock_mon = MagicMock()
    mock_mon.CurrentBrightness = 65

    with patch("nova.skills.system.display._get_wmi_monitor", return_value=([MagicMock()], [mock_mon])):
        res = skill.execute({"action": "get_brightness"})
        assert res["status"] == "ok"
        assert res["brightness"] == 65
        assert "65%" in res["message"]


def test_get_brightness_unsupported_hardware(skill: DisplaySkill):
    """get_brightness returns status='unsupported' when WMI methods are missing."""
    with patch("nova.skills.system.display._get_wmi_monitor", return_value=(None, None)):
        res = skill.execute({"action": "get_brightness"})
        assert res["status"] == "unsupported"
        assert "external monitor" in res["message"].lower() or "not available" in res["message"].lower()


def test_set_brightness_with_readback(skill: DisplaySkill):
    """set_brightness sets brightness and performs read-back verification."""
    mock_method = MagicMock()
    mock_mon = MagicMock()
    mock_mon.CurrentBrightness = 80

    with patch("nova.skills.system.display._get_wmi_monitor", return_value=([mock_method], [mock_mon])):
        res = skill.execute({"action": "set_brightness", "level": 80})
        assert res["status"] == "ok"
        assert res["brightness"] == 80
        assert res["verified"] is True
        mock_method.WmiSetBrightness.assert_called_once_with(80, 0)


def test_adjust_brightness_delta(skill: DisplaySkill):
    """increase_brightness adjusts brightness by amount with read-back verification."""
    mock_method = MagicMock()
    mock_mon = MagicMock()
    mock_mon.CurrentBrightness = 50

    def mock_get_wmi():
        return [mock_method], [mock_mon]

    with patch("nova.skills.system.display._get_wmi_monitor", side_effect=mock_get_wmi):
        res = skill.execute({"action": "increase_brightness", "amount": 15})
        assert res["status"] == "ok"
        assert res["delta"] == 15
        assert "increased" in res["action"]
        mock_method.WmiSetBrightness.assert_called_once_with(65, 0)


# ============================================================================
# 5. Night Light Unit Tests
# ============================================================================


def test_night_light_honest_restriction(skill: DisplaySkill):
    """Night Light must return status='restricted', open ms-settings:nightlight, and never fake success."""
    with patch("os.startfile", create=True) as mock_startfile:
        res = skill.execute({"action": "night_light"})
        assert res["status"] == "restricted"
        assert res["action"] == "navigated"
        assert res["target_uri"] == "ms-settings:nightlight"
        assert "restricted" in res["status"]
        assert "CloudStore" in res["message"] or "restricts" in res["message"]
        mock_startfile.assert_called_once_with("ms-settings:nightlight")


# ============================================================================
# 6. Display Mode & CDS_TEST Unit Tests
# ============================================================================


def test_devmodew_structure_size():
    """DEVMODEW ctypes structure must have exact Win32 size (220 bytes)."""
    dm = DEVMODEW()
    assert dm.dmSize == 0
    import ctypes
    assert ctypes.sizeof(DEVMODEW) == 220


def test_set_resolution_unsupported_mode(skill: DisplaySkill):
    """set_resolution rejects mode not present in supported modes list."""
    supported_mock = [{"width": 1920, "height": 1080, "refresh_rate": 60, "bits_per_pel": 32}]
    with patch("nova.skills.system.display._get_supported_modes", return_value=supported_mock):
        res = skill.execute({"action": "set_resolution", "width": 1234, "height": 567})
        assert res["status"] == "unsupported"
        assert "not supported" in res["message"]


def test_set_resolution_cds_test_failed(skill: DisplaySkill):
    """When CDS_TEST returns failure, mode is not applied and navigation is offered."""
    supported_mock = [{"width": 1920, "height": 1080, "refresh_rate": 60, "bits_per_pel": 32}]
    with patch("nova.skills.system.display._get_supported_modes", return_value=supported_mock), \
         patch("ctypes.windll.user32.ChangeDisplaySettingsExW", return_value=DISP_CHANGE_FAILED), \
         patch("os.startfile", create=True) as mock_startfile:
        res = skill.execute({"action": "set_resolution", "width": 1920, "height": 1080})
        assert res["status"] == "restricted"
        assert res["action"] == "navigated"
        assert res["target_uri"] == "ms-settings:display"
        assert "CDS_TEST" in res["message"]
        mock_startfile.assert_called_once_with("ms-settings:display")


def test_set_orientation_cds_test_failed(skill: DisplaySkill):
    """When orientation change fails CDS_TEST, navigation is offered."""
    with patch("ctypes.windll.user32.ChangeDisplaySettingsExW", return_value=DISP_CHANGE_FAILED), \
         patch("os.startfile", create=True) as mock_startfile:
        res = skill.execute({"action": "set_orientation", "orientation": "portrait"})
        assert res["status"] == "restricted"
        assert res["action"] == "navigated"
        assert res["target_uri"] == "ms-settings:display"
        mock_startfile.assert_called_once_with("ms-settings:display")
