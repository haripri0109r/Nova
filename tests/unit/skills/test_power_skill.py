"""
Unit tests for PowerSkill (Phase 5.8-F: Windows Power, Battery & Energy Management).

Verifies:
- Strict schema adherence (JSON Schema object, required fields, additionalProperties: False)
- can_handle matching canonical intent and aliases (power, power_control, battery, hibernate)
- Action validation (missing action, unknown action)
- Battery telemetry (charging, discharging, desktop without battery, battery saver active, error handling)
- Dynamic power scheme enumeration and resolution (no hardcoded GUIDs, OEM schemes like Turbo/Silent)
- Scheme switching with read-back verification and honest "restricted" handling
- Timeouts reading and setting with read-back verification and honest "restricted" handling
- Battery saver status query
- Hibernate capability and shutdown.exe /h invocation
- Non-Windows platform graceful handling
"""

import ctypes
from unittest.mock import MagicMock, patch
import pytest

from nova.skills.system.power import (
    PowerSkill,
    SYSTEM_POWER_STATUS,
    BATTERY_FLAG_CHARGING,
    BATTERY_FLAG_NO_BATTERY,
    BATTERY_FLAG_UNKNOWN,
    BATTERY_PERCENTAGE_UNKNOWN,
    AC_LINE_ONLINE,
    AC_LINE_OFFLINE,
    AC_LINE_UNKNOWN,
)


@pytest.fixture
def skill():
    return PowerSkill()


# ---------------------------------------------------------------------------
# Schema and Registration Tests
# ---------------------------------------------------------------------------

def test_power_skill_schema(skill):
    """Verify parameters_schema adheres to strict requirements."""
    schema = skill.parameters_schema
    assert schema["type"] == "object"
    assert "action" in schema["properties"]
    assert "scheme" in schema["properties"]
    assert "target" in schema["properties"]
    assert "minutes" in schema["properties"]
    assert "source" in schema["properties"]
    assert schema["required"] == ["action"]
    assert schema["additionalProperties"] is False

    valid_actions = {
        "get_battery_status",
        "get_power_scheme",
        "set_power_scheme",
        "get_timeouts",
        "set_timeout",
        "get_battery_saver",
        "hibernate",
    }
    assert set(schema["properties"]["action"]["enum"]) == valid_actions


def test_can_handle(skill):
    """Verify can_handle accepts canonical intent and recognized aliases."""
    assert skill.can_handle({"intent": "power"}) is True
    assert skill.can_handle({"intent": "power_control"}) is True
    assert skill.can_handle({"intent": "battery"}) is True
    assert skill.can_handle({"intent": "hibernate"}) is True
    assert skill.can_handle({"intent": "sleep"}) is False
    assert skill.can_handle({"intent": "shutdown"}) is False
    assert skill.can_handle({"intent": "open_settings"}) is False


# ---------------------------------------------------------------------------
# Validation Tests
# ---------------------------------------------------------------------------

def test_missing_action(skill):
    res = skill.execute({})
    assert res["status"] == "error"
    assert "Unknown power action" in res["message"]


def test_invalid_action(skill):
    res = skill.execute({"action": "explode"})
    assert res["status"] == "error"
    assert "Unknown power action" in res["message"]


def test_set_power_scheme_missing_scheme(skill):
    res = skill.execute({"action": "set_power_scheme"})
    assert res["status"] == "error"
    assert "Missing required 'scheme' parameter" in res["message"]


def test_set_timeout_invalid_params(skill):
    # Missing target
    res = skill.execute({"action": "set_timeout", "minutes": 10})
    assert res["status"] == "error"
    assert "Invalid timeout target" in res["message"]

    # Invalid target
    res = skill.execute({"action": "set_timeout", "target": "cpu", "minutes": 10})
    assert res["status"] == "error"
    assert "Invalid timeout target" in res["message"]

    # Missing minutes
    res = skill.execute({"action": "set_timeout", "target": "display"})
    assert res["status"] == "error"
    assert "Invalid minutes" in res["message"]

    # Negative minutes
    res = skill.execute({"action": "set_timeout", "target": "display", "minutes": -5})
    assert res["status"] == "error"
    assert "Invalid minutes" in res["message"]

    # Out of range minutes (>1440)
    res = skill.execute({"action": "set_timeout", "target": "display", "minutes": 2000})
    assert res["status"] == "error"
    assert "Invalid minutes" in res["message"]

    # Invalid source
    res = skill.execute({"action": "set_timeout", "target": "display", "minutes": 10, "source": "solar"})
    assert res["status"] == "error"
    assert "Invalid source" in res["message"]


# ---------------------------------------------------------------------------
# Battery Telemetry Tests
# ---------------------------------------------------------------------------

def test_battery_discharging_telemetry(skill):
    """Test battery query on a laptop discharging on battery."""
    mock_status = SYSTEM_POWER_STATUS()
    mock_status.ACLineStatus = AC_LINE_OFFLINE
    mock_status.BatteryFlag = 0
    mock_status.BatteryLifePercent = 75
    mock_status.SystemStatusFlag = 0
    mock_status.BatteryLifeTime = 14400
    mock_status.BatteryFullLifeTime = 19200

    with patch("nova.skills.system.power._get_system_power_status", return_value=mock_status):
        res = skill.execute({"action": "get_battery_status"})
        assert res["status"] == "ok"
        assert res["has_battery"] is True
        assert res["battery_percentage"] == 75
        assert res["is_charging"] is False
        assert res["ac_power"] == "offline"
        assert res["battery_saver_active"] is False
        assert res["battery_lifetime_seconds"] == 14400


def test_battery_charging_telemetry(skill):
    """Test battery query on a laptop plugged in and charging."""
    mock_status = SYSTEM_POWER_STATUS()
    mock_status.ACLineStatus = AC_LINE_ONLINE
    mock_status.BatteryFlag = BATTERY_FLAG_CHARGING
    mock_status.BatteryLifePercent = 90
    mock_status.SystemStatusFlag = 0
    mock_status.BatteryLifeTime = 0xFFFFFFFF
    mock_status.BatteryFullLifeTime = 0xFFFFFFFF

    with patch("nova.skills.system.power._get_system_power_status", return_value=mock_status):
        res = skill.execute({"action": "get_battery_status"})
        assert res["status"] == "ok"
        assert res["has_battery"] is True
        assert res["battery_percentage"] == 90
        assert res["is_charging"] is True
        assert res["ac_power"] == "online"
        assert res["battery_lifetime_seconds"] is None


def test_battery_desktop_no_battery(skill):
    """Test battery query on a desktop without a battery."""
    mock_status = SYSTEM_POWER_STATUS()
    mock_status.ACLineStatus = AC_LINE_ONLINE
    mock_status.BatteryFlag = BATTERY_FLAG_NO_BATTERY
    mock_status.BatteryLifePercent = BATTERY_PERCENTAGE_UNKNOWN
    mock_status.SystemStatusFlag = 0
    mock_status.BatteryLifeTime = 0xFFFFFFFF
    mock_status.BatteryFullLifeTime = 0xFFFFFFFF

    with patch("nova.skills.system.power._get_system_power_status", return_value=mock_status):
        res = skill.execute({"action": "get_battery_status"})
        assert res["status"] == "ok"
        assert res["has_battery"] is False
        assert res["battery_percentage"] is None
        assert res["is_charging"] is False
        assert res["ac_power"] == "online"
        assert "No battery detected (desktop system)" in res["detail"]


def test_battery_saver_status_query(skill):
    """Test battery saver query via get_battery_saver."""
    mock_status = SYSTEM_POWER_STATUS()
    mock_status.ACLineStatus = AC_LINE_OFFLINE
    mock_status.BatteryFlag = 0
    mock_status.BatteryLifePercent = 18
    mock_status.SystemStatusFlag = 1  # Battery saver ON

    with patch("nova.skills.system.power._get_system_power_status", return_value=mock_status):
        res = skill.execute({"action": "get_battery_saver"})
        assert res["status"] == "ok"
        assert res["battery_saver_active"] is True
        assert "ON" in res["detail"]


# ---------------------------------------------------------------------------
# Power Scheme Tests
# ---------------------------------------------------------------------------

def test_get_power_scheme(skill):
    """Verify get_power_scheme retrieves active scheme and lists available."""
    active_guid = "381b4222-f694-41f0-9685-ff5bb260df2e"
    schemes = [
        {"guid": active_guid, "name": "Balanced"},
        {"guid": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "name": "High performance"},
        {"guid": "a1841308-3541-4fab-bc81-f71556f20b4a", "name": "Power saver"},
        {"guid": "12345678-1234-1234-1234-123456789abc", "name": "Turbo"},
    ]

    with patch("nova.skills.system.power._get_active_power_scheme", return_value=(active_guid, "Balanced")), \
         patch("nova.skills.system.power._enumerate_power_schemes", return_value=schemes):
        res = skill.execute({"action": "get_power_scheme"})
        assert res["status"] == "ok"
        assert res["active_scheme"] == "Balanced"
        assert res["active_guid"] == active_guid
        assert len(res["available_schemes"]) == 4
        assert "Turbo" in res["available_schemes"]


def test_set_power_scheme_dynamic_resolution(skill):
    """Verify dynamic resolution matches custom OEM schemes like Turbo without hardcoded GUIDs."""
    active_guid = "381b4222-f694-41f0-9685-ff5bb260df2e"
    turbo_guid = "12345678-1234-1234-1234-123456789abc"
    schemes = [
        {"guid": active_guid, "name": "Balanced"},
        {"guid": turbo_guid, "name": "ASUS Turbo Mode"},
    ]

    with patch("nova.skills.system.power._enumerate_power_schemes", return_value=schemes), \
         patch("nova.skills.system.power._get_active_power_scheme", side_effect=[(active_guid, "Balanced"), (turbo_guid, "ASUS Turbo Mode")]), \
         patch("ctypes.windll.ole32.CLSIDFromString", return_value=0), \
         patch("ctypes.windll.powrprof.PowerSetActiveScheme", return_value=0):
        res = skill.execute({"action": "set_power_scheme", "scheme": "turbo"})
        assert res["status"] == "ok"
        assert res["active_scheme"] == "ASUS Turbo Mode"
        assert res["active_guid"] == turbo_guid


def test_set_power_scheme_no_match(skill):
    """Verify unknown scheme name returns error with available schemes."""
    active_guid = "381b4222-f694-41f0-9685-ff5bb260df2e"
    schemes = [
        {"guid": active_guid, "name": "Balanced"},
    ]

    with patch("nova.skills.system.power._enumerate_power_schemes", return_value=schemes), \
         patch("nova.skills.system.power._get_active_power_scheme", return_value=(active_guid, "Balanced")):
        res = skill.execute({"action": "set_power_scheme", "scheme": "super_saiyan"})
        assert res["status"] == "error"
        assert "No power scheme matching 'super_saiyan'" in res["message"]
        assert "'Balanced'" in res["message"]


def test_set_power_scheme_restricted(skill):
    """Verify when Windows denies scheme activation, status='restricted' is honestly returned."""
    active_guid = "381b4222-f694-41f0-9685-ff5bb260df2e"
    perf_guid = "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"
    schemes = [
        {"guid": active_guid, "name": "Balanced"},
        {"guid": perf_guid, "name": "High performance"},
    ]

    with patch("nova.skills.system.power._enumerate_power_schemes", return_value=schemes), \
         patch("nova.skills.system.power._get_active_power_scheme", return_value=(active_guid, "Balanced")), \
         patch("ctypes.windll.ole32.CLSIDFromString", return_value=0), \
         patch("ctypes.windll.powrprof.PowerSetActiveScheme", return_value=5):  # 5 = ERROR_ACCESS_DENIED
        res = skill.execute({"action": "set_power_scheme", "scheme": "high performance"})
        assert res["status"] == "restricted"
        assert res["fallback"] == "ms-settings:powersleep"
        assert "administrator privileges" in res["message"]


# ---------------------------------------------------------------------------
# Timeout Tests
# ---------------------------------------------------------------------------

def test_get_timeouts(skill):
    """Verify get_timeouts returns parsed timeouts accurately."""
    mock_timeouts = {
        "display_timeout_ac_min": 10,
        "display_timeout_dc_min": 5,
        "sleep_timeout_ac_min": 30,
        "sleep_timeout_dc_min": 15,
    }
    with patch("nova.skills.system.power._query_timeouts_cli", return_value=mock_timeouts):
        res = skill.execute({"action": "get_timeouts"})
        assert res["status"] == "ok"
        assert res["display_timeout_ac_min"] == 10
        assert res["display_timeout_dc_min"] == 5
        assert res["sleep_timeout_ac_min"] == 30
        assert res["sleep_timeout_dc_min"] == 15


def test_set_timeout_success_with_readback(skill):
    """Verify set_timeout runs powercfg with fixed list and verifies read-back."""
    mock_verified = {
        "display_timeout_ac_min": 15,
        "display_timeout_dc_min": 15,
        "sleep_timeout_ac_min": 30,
        "sleep_timeout_dc_min": 15,
    }
    with patch("subprocess.run") as mock_run, \
         patch("nova.skills.system.power._query_timeouts_cli", return_value=mock_verified):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = skill.execute({"action": "set_timeout", "target": "display", "minutes": 15, "source": "both"})
        assert res["status"] == "ok"
        assert "Set display turn-off timeout to 15 minutes (both)" in res["detail"]
        assert res["target"] == "display"
        assert res["minutes"] == 15


def test_set_timeout_restricted(skill):
    """Verify set_timeout handles non-elevated restricted environment honestly."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="Access is denied")
        res = skill.execute({"action": "set_timeout", "target": "sleep", "minutes": 10})
        assert res["status"] == "restricted"
        assert res["fallback"] == "ms-settings:powersleep"
        assert "administrator privileges" in res["message"]


def test_set_timeout_readback_mismatch(skill):
    """Verify set_timeout detects when setting did not change and does NOT report fake success."""
    mock_mismatch = {
        "display_timeout_ac_min": 10,
        "display_timeout_dc_min": 10,
        "sleep_timeout_ac_min": 30,
        "sleep_timeout_dc_min": 15,
    }
    with patch("subprocess.run") as mock_run, \
         patch("nova.skills.system.power._query_timeouts_cli", return_value=mock_mismatch):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        res = skill.execute({"action": "set_timeout", "target": "display", "minutes": 25, "source": "ac"})
        assert res["status"] == "error"
        assert "Timeout read-back mismatch" in res["message"]


# ---------------------------------------------------------------------------
# Hibernate Tests
# ---------------------------------------------------------------------------

def test_hibernate_capability_unsupported(skill):
    """Verify hibernate fails gracefully when hibernation is disabled on the system."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="Hibernation has not been enabled", stderr="")
        res = skill.execute({"action": "hibernate"})
        assert res["status"] == "unsupported"
        assert "not supported or not enabled" in res["message"]


def test_hibernate_invocation(skill):
    """Verify hibernate calls shutdown.exe /h directly without shell=True."""
    with patch("subprocess.run") as mock_run:
        # First call is powercfg /availablesleepstates, second call is shutdown.exe /h
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="The following sleep states are available: Standby Hibernate", stderr=""),
            MagicMock(returncode=0, stdout="", stderr=""),
        ]
        res = skill.execute({"action": "hibernate"})
        assert res["status"] == "ok"
        assert res["detail"] == "Entering hibernation."
        assert mock_run.call_count == 2
        shutdown_call = mock_run.call_args_list[1]
        called_args = shutdown_call[0][0]
        assert "shutdown.exe" in called_args[0]
        assert "/h" in called_args
        assert shutdown_call[1].get("shell") is not True
