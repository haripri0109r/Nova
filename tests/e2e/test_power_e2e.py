"""
Real Windows End-to-End Test Suite for Phase 5.8-F: Windows Power, Battery & Energy Management.

Verifies real Windows execution of PowerSkill against actual hardware and Windows APIs:
1. Real battery telemetry query (GetSystemPowerStatus):
   - Truthful AC state, battery presence, battery %, charging state.
   - Works on laptops with batteries and desktops without batteries.
2. Real active power scheme and dynamic enumeration (PowerGetActiveScheme / PowerEnumerate):
   - Discovers current active scheme and available OEM schemes without hardcoded GUIDs.
3. Real timeout queries (powercfg):
   - Discovers display and sleep timeouts for AC and DC.
4. Real battery/energy saver query:
   - Queries battery saver status honestly.
5. Hibernation capability and RiskLevel gating:
   - Verifies hibernation check without executing shutdown.exe /h.
   - Verifies StepRiskPolicy classifies power/hibernate as RiskLevel.HIGH requiring confirmation.
6. Mutation tests with honest restricted handling:
   - On standard non-elevated Windows accounts, verifies status="restricted" with fallback="ms-settings:powersleep".
   - If elevated and permitted, verifies mutation with read-back and restores original state.
7. End-to-end pipeline:
   - User Text -> Brain Classifier -> Deterministic Safe Planner -> PowerSkill -> Real Windows API.
"""

from __future__ import annotations

import sys
import pytest

from nova.brain.engine import BrainEngine
from nova.brain.models import RecognizedInput
from nova.brain.planner import get_planner
from nova.brain.types import IntentCategory
from nova.skills.registry import registry
from nova.skills.system.power import PowerSkill
from nova.agent.step_risk_policy import classify_step_risk, RiskLevel


@pytest.fixture
def power_skill() -> PowerSkill:
    return PowerSkill()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_battery_telemetry(power_skill: PowerSkill):
    """Test real battery telemetry query via GetSystemPowerStatus."""
    res = power_skill.execute({"action": "get_battery_status"})
    assert res["status"] == "ok"
    assert "has_battery" in res
    assert "ac_power" in res
    assert "is_charging" in res
    assert "battery_saver_active" in res

    if res["has_battery"]:
        assert isinstance(res["battery_percentage"], int)
        assert 0 <= res["battery_percentage"] <= 100
    else:
        # Desktop or machine with no battery
        assert res["battery_percentage"] is None
        assert res["is_charging"] is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_power_scheme_query(power_skill: PowerSkill):
    """Test real power scheme query via Win32 Power APIs."""
    res = power_skill.execute({"action": "get_power_scheme"})
    assert res["status"] == "ok"
    assert "active_guid" in res
    assert len(res["active_guid"]) == 36
    assert "active_scheme" in res
    assert len(res["active_scheme"]) > 0

    available = res.get("available_schemes", [])
    assert len(available) >= 1
    assert any(res["active_scheme"].lower() in s.lower() for s in available)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_timeouts_query(power_skill: PowerSkill):
    """Test real timeout queries via powercfg."""
    res = power_skill.execute({"action": "get_timeouts"})
    assert res["status"] == "ok"
    assert "display_timeout_ac_min" in res
    assert "display_timeout_dc_min" in res
    assert "sleep_timeout_ac_min" in res
    assert "sleep_timeout_dc_min" in res
    assert isinstance(res["display_timeout_ac_min"], int)
    assert isinstance(res["sleep_timeout_ac_min"], int)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_battery_saver_query(power_skill: PowerSkill):
    """Test real battery saver status query."""
    res = power_skill.execute({"action": "get_battery_saver"})
    assert res["status"] == "ok"
    assert "battery_saver_active" in res
    assert isinstance(res["battery_saver_active"], bool)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_hibernation_capability_and_risk(power_skill: PowerSkill):
    """
    Test hibernation detection and StepRiskPolicy gating.
    Do NOT execute hibernation in automated tests.
    """
    # Test hibernation capability check without invoking shutdown.exe /h
    is_supported = power_skill._is_hibernation_enabled()
    assert isinstance(is_supported, bool)

    # StepRiskPolicy gating
    risk = classify_step_risk("power", {"action": "hibernate"})
    assert risk == RiskLevel.HIGH

    # Non-destructive actions are LOW
    assert classify_step_risk("power", {"action": "get_battery_status"}) == RiskLevel.LOW
    assert classify_step_risk("power", {"action": "get_power_scheme"}) == RiskLevel.LOW
    assert classify_step_risk("power", {"action": "set_timeout", "target": "display", "minutes": 10}) == RiskLevel.LOW


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_scheme_mutation_or_honest_restriction(power_skill: PowerSkill):
    """
    Attempt scheme activation with current scheme.
    If non-elevated: must return status="restricted" with fallback="ms-settings:powersleep".
    If elevated: must return status="ok" with verified read-back.
    """
    current_res = power_skill.execute({"action": "get_power_scheme"})
    assert current_res["status"] == "ok"
    current_name = current_res["active_scheme"]

    res = power_skill.execute({"action": "set_power_scheme", "scheme": current_name})
    if res["status"] == "restricted":
        assert res["fallback"] == "ms-settings:powersleep"
        assert "administrator" in res["message"].lower() or "denied" in res["message"].lower()
    else:
        assert res["status"] == "ok"
        assert res["active_scheme"].lower() == current_name.lower()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
def test_real_windows_timeout_mutation_or_honest_restriction(power_skill: PowerSkill):
    """
    Attempt timeout mutation.
    If non-elevated: must return status="restricted" with fallback="ms-settings:powersleep".
    If elevated: must return status="ok" with verified read-back and restore.
    """
    timeouts_res = power_skill.execute({"action": "get_timeouts"})
    assert timeouts_res["status"] == "ok"
    orig_ac = timeouts_res["display_timeout_ac_min"]

    # Attempt to set display timeout to current value
    res = power_skill.execute({"action": "set_timeout", "target": "display", "minutes": orig_ac, "source": "ac"})
    if res["status"] == "restricted":
        assert res["fallback"] == "ms-settings:powersleep"
    else:
        assert res["status"] == "ok"
        assert res["minutes"] == orig_ac


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "win32", reason="Windows-only real E2E test")
async def test_real_windows_power_full_pipeline():
    """
    Test full end-to-end flow:
    Natural language command -> Intent Classification -> Safe Deterministic Planner -> Real PowerSkill Execution.
    """
    engine = BrainEngine()
    await engine.initialize()
    planner = get_planner()
    await planner.initialize()

    cmd = "what is my battery level"
    input_model = RecognizedInput(text=cmd)
    intent = await engine._intent_classifier.classify(input_model)
    assert intent.category == IntentCategory.POWER
    assert intent.entities.get("action") == "get_battery_status"

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    step = plan.steps[0]
    assert step.tool == "power"
    assert step.parameters == {"action": "get_battery_status"}

    skill = registry.get("power")
    assert skill is not None
    result = skill.execute(step.parameters)
    assert result["status"] == "ok"
    assert "has_battery" in result
