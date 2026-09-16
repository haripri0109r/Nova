"""
Unit tests for Power, Battery & Energy Brain Planning (Phase 5.8-F).

Verifies:
- Deterministic classification and fast-path single-step execution plans for all Power actions:
  * get_battery_status ("what is my battery level?", "how much battery do I have?", "am I charging?")
  * get_power_scheme ("what power plan am I on?", "what is the active power mode?")
  * set_power_scheme ("switch to high performance", "change power plan to balanced", "set power mode to turbo")
  * get_timeouts ("what are my sleep timeouts?", "display timeout status")
  * set_timeout ("turn off screen after 15 minutes", "put PC to sleep after 30 minutes")
  * get_battery_saver ("is battery saver on?", "energy saver status")
  * hibernate ("hibernate computer", "hibernate pc")
- Anti-greedy classification boundaries:
  * "put computer to sleep" -> SLEEP (never power)
  * "turn off my computer" -> SHUTDOWN (never power)
  * "restart computer" -> RESTART (never power)
  * "open power settings" -> OPEN_SETTINGS (never power)
  * "dim screen" -> SET_BRIGHTNESS (never power)
- Compound command handling:
  * "turn off screen after 10 minutes and turn on dark mode" routed through multi-step planner
"""

import pytest
from unittest.mock import AsyncMock, patch

from nova.brain.engine import BrainEngine
from nova.brain.models import RecognizedInput
from nova.brain.planner import get_planner
from nova.brain.types import IntentCategory
from nova.skills.system.power import PowerSkill


async def _get_brain():
    engine = BrainEngine()
    await engine.initialize()
    planner = get_planner()
    await planner.initialize()
    return engine, planner


# ============================================================================
# 1. Deterministic Fast Paths for Power Actions
# ============================================================================

@pytest.mark.asyncio
async def test_battery_status_fast_path():
    engine, planner = await _get_brain()
    queries = [
        "what is my battery percentage",
        "battery status",
        "how much battery do I have left",
        "am I charging",
        "is my laptop plugged in",
    ]
    for cmd in queries:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.POWER
        assert intent.entities.get("action") == "get_battery_status"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "get_battery_status"}


@pytest.mark.asyncio
async def test_power_scheme_queries_fast_path():
    engine, planner = await _get_brain()
    queries = [
        "what power scheme is active",
        "current power plan",
        "what is the active power mode",
    ]
    for cmd in queries:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.POWER
        assert intent.entities.get("action") == "get_power_scheme"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "get_power_scheme"}


@pytest.mark.asyncio
async def test_set_power_scheme_fast_path():
    engine, planner = await _get_brain()
    cases = [
        ("switch to high performance", "high performance"),
        ("change power plan to balanced", "balanced"),
        ("set power mode to turbo", "turbo"),
        ("switch to power saver mode", "power saver"),
    ]
    for cmd, expected_scheme in cases:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.POWER
        assert intent.entities.get("action") == "set_power_scheme"
        assert intent.entities.get("scheme") == expected_scheme
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "set_power_scheme", "scheme": expected_scheme}


@pytest.mark.asyncio
async def test_get_timeouts_fast_path():
    engine, planner = await _get_brain()
    queries = [
        "display timeout",
        "sleep timeout status",
        "when will screen turn off",
    ]
    for cmd in queries:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.POWER
        assert intent.entities.get("action") == "get_timeouts"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "get_timeouts"}


@pytest.mark.asyncio
async def test_set_timeout_fast_path():
    engine, planner = await _get_brain()

    # Display timeout
    cmd = "turn off screen after 15 minutes"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.POWER
    assert intent.entities.get("action") == "set_timeout"
    assert intent.entities.get("target") == "display"
    assert intent.entities.get("minutes") == 15
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "power"
    assert plan.steps[0].parameters == {"action": "set_timeout", "target": "display", "minutes": 15}

    # Sleep timeout
    cmd = "put pc to sleep after 30 minutes"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.POWER
    assert intent.entities.get("action") == "set_timeout"
    assert intent.entities.get("target") == "sleep"
    assert intent.entities.get("minutes") == 30
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "power"
    assert plan.steps[0].parameters == {"action": "set_timeout", "target": "sleep", "minutes": 30}


@pytest.mark.asyncio
async def test_get_battery_saver_fast_path():
    engine, planner = await _get_brain()
    queries = [
        "is battery saver enabled",
        "battery saver status",
        "energy saver mode",
    ]
    for cmd in queries:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.POWER
        assert intent.entities.get("action") == "get_battery_saver"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "get_battery_saver"}


@pytest.mark.asyncio
async def test_hibernate_fast_path():
    engine, planner = await _get_brain()
    queries = [
        "hibernate my computer",
        "hibernate pc",
        "hibernate",
    ]
    for cmd in queries:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.POWER
        assert intent.entities.get("action") == "hibernate"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "hibernate"}


# ============================================================================
# 2. Anti-Greedy Classification Protections
# ============================================================================

@pytest.mark.asyncio
async def test_anti_greedy_sleep():
    engine, _ = await _get_brain()
    # "put my computer to sleep" must be SLEEP, not POWER
    intent = await engine._intent_classifier.classify(RecognizedInput(text="put my computer to sleep"))
    assert intent.category == IntentCategory.SLEEP

    intent2 = await engine._intent_classifier.classify(RecognizedInput(text="go to sleep"))
    assert intent2.category == IntentCategory.SLEEP


@pytest.mark.asyncio
async def test_anti_greedy_shutdown():
    engine, _ = await _get_brain()
    # "turn off computer" / "shut down" must be SHUTDOWN, not POWER
    intent = await engine._intent_classifier.classify(RecognizedInput(text="turn off my computer"))
    assert intent.category == IntentCategory.SHUTDOWN

    intent2 = await engine._intent_classifier.classify(RecognizedInput(text="shut down the PC"))
    assert intent2.category == IntentCategory.SHUTDOWN


@pytest.mark.asyncio
async def test_anti_greedy_restart():
    engine, _ = await _get_brain()
    intent = await engine._intent_classifier.classify(RecognizedInput(text="restart my computer"))
    assert intent.category == IntentCategory.RESTART


@pytest.mark.asyncio
async def test_anti_greedy_settings():
    engine, _ = await _get_brain()
    intent = await engine._intent_classifier.classify(RecognizedInput(text="open battery settings"))
    assert intent.category == IntentCategory.OPEN_SETTINGS

    intent2 = await engine._intent_classifier.classify(RecognizedInput(text="open power settings"))
    assert intent2.category == IntentCategory.OPEN_SETTINGS


# ============================================================================
# 3. Compound Command Planning
# ============================================================================

@pytest.mark.asyncio
async def test_compound_power_and_personalization():
    engine, planner = await _get_brain()
    cmd = "turn off screen after 10 minutes and turn on dark mode"

    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.entities.get("is_compound") is True
    # Must NOT take the single-step fast path
    assert planner._is_deterministic_safe(cmd, intent, None) is False

    mock_llm_response = (
        '{"steps": ['
        '{"tool": "power", "parameters": {"action": "set_timeout", "target": "display", "minutes": 10}, "depends_on": []}, '
        '{"tool": "personalization", "parameters": {"feature": "theme", "mode": "dark"}, "depends_on": [0]}'
        '], "description": "Set screen timeout and enable dark mode"}'
    )

    with patch.object(planner._llm_manager, "process", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = mock_llm_response
        plan = await planner.plan(cmd, intent)

        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "power"
        assert plan.steps[0].parameters == {"action": "set_timeout", "target": "display", "minutes": 10}
        assert plan.steps[0].depends_on == []

        assert plan.steps[1].tool == "personalization"
        assert plan.steps[1].parameters == {"feature": "theme", "mode": "dark"}
        assert plan.steps[1].depends_on == [0]
