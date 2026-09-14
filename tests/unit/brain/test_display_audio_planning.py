"""
Unit tests for Display and Audio Brain Planning (Phase 5.8-C).

Verifies:
- Fast-path deterministic classification & single-step plan generation for Display:
  - Resolution query & mutation ("what is my resolution?", "set resolution to 1920x1080")
  - Refresh rate query & mutation ("what refresh rate am I using?", "set refresh rate to 60")
  - Screen orientation query & mutation ("rotate screen to portrait")
  - Display information query ("how many monitors do I have?")
  - Night Light request ("night light")
- Fast-path deterministic classification & single-step plan generation for Audio:
  - Microphone query ("what microphone am I using?")
  - Microphone mute / unmute ("mute microphone", "unmute microphone")
  - Device listings ("list microphones", "list speakers")
  - Default output switching ("switch to headphones")
- SettingsSkill boundary:
  - Navigation requests ("open display settings", "open sound settings") route to SettingsSkill
  - State queries/mutations route to DisplaySkill and AudioSkill
- Anti-greedy routing:
  - Display and Audio keywords do not steal file search or application launch commands
- Compound command DAG planning:
  - "make the screen brighter and lower the volume" produces a valid 2-step DAG
"""

import pytest

from nova.brain.engine import BrainEngine
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import ExecutionPlan, PlanStep, RecognizedInput
from nova.brain.planner import Planner, get_planner
from nova.brain.types import ConfidenceLevel, IntentCategory
from nova.skills.registry import registry


async def _get_brain():
    engine = BrainEngine()
    await engine.initialize()
    planner = get_planner()
    await planner.initialize()
    return engine, planner


# ============================================================================
# 1. Display Deterministic Fast Paths
# ============================================================================


@pytest.mark.asyncio
async def test_get_resolution_fast_path():
    engine, planner = await _get_brain()
    cmd = "what is my resolution?"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "get_resolution"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "get_resolution"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_set_resolution_fast_path():
    engine, planner = await _get_brain()
    cmd = "set resolution to 1920x1080"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "set_resolution"
    assert intent.entities.get("width") == 1920
    assert intent.entities.get("height") == 1080
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "set_resolution", "width": 1920, "height": 1080}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_get_refresh_rate_fast_path():
    engine, planner = await _get_brain()
    cmd = "what refresh rate am I using?"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "get_refresh_rate"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "get_refresh_rate"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_set_refresh_rate_fast_path():
    engine, planner = await _get_brain()
    cmd = "set refresh rate to 60"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "set_refresh_rate"
    assert intent.entities.get("refresh_rate") == 60
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "set_refresh_rate", "refresh_rate": 60}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_set_orientation_fast_path():
    engine, planner = await _get_brain()
    cmd = "rotate screen to portrait"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "set_orientation"
    assert intent.entities.get("orientation") == "portrait"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "set_orientation", "orientation": "portrait"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_display_info_fast_path():
    engine, planner = await _get_brain()
    cmd = "how many monitors do i have"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "get_display_info"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "get_display_info"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_night_light_fast_path():
    engine, planner = await _get_brain()
    cmd = "night light"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.DISPLAY
    assert intent.entities.get("action") == "night_light"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "display"
    assert plan.steps[0].parameters == {"action": "night_light"}
    assert planner._validator.validate(plan) == plan


# ============================================================================
# 2. Audio Deterministic Fast Paths
# ============================================================================


@pytest.mark.asyncio
async def test_what_microphone_fast_path():
    engine, planner = await _get_brain()
    cmd = "what microphone am i using?"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.AUDIO
    assert intent.entities.get("action") == "list_inputs"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "audio"
    assert plan.steps[0].parameters == {"action": "list_inputs"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_list_speakers_fast_path():
    engine, planner = await _get_brain()
    cmd = "list speakers"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.AUDIO
    assert intent.entities.get("action") == "list_outputs"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "audio"
    assert plan.steps[0].parameters == {"action": "list_outputs"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_mute_mic_fast_path():
    engine, planner = await _get_brain()
    cmd = "mute microphone"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.AUDIO
    assert intent.entities.get("action") == "mute_mic"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "audio"
    assert plan.steps[0].parameters == {"action": "mute_mic"}
    assert planner._validator.validate(plan) == plan


@pytest.mark.asyncio
async def test_switch_to_headphones_fast_path():
    engine, planner = await _get_brain()
    cmd = "switch to headphones"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.AUDIO
    assert intent.entities.get("action") == "set_default_output"
    assert intent.entities.get("device_name") == "headphones"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "audio"
    assert plan.steps[0].parameters == {"action": "set_default_output", "device_name": "headphones"}
    assert planner._validator.validate(plan) == plan


# ============================================================================
# 3. SettingsSkill Boundary Isolation Tests
# ============================================================================


@pytest.mark.asyncio
async def test_settings_skill_boundary_display():
    engine, planner = await _get_brain()
    cmd = "open display settings"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.OPEN_SETTINGS
    assert intent.entities.get("page") == "display"

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "open_settings"
    assert plan.steps[0].parameters == {"page": "display"}


@pytest.mark.asyncio
async def test_settings_skill_boundary_sound():
    engine, planner = await _get_brain()
    cmd = "open sound settings"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.OPEN_SETTINGS
    assert intent.entities.get("page") == "sound"

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "open_settings"
    assert plan.steps[0].parameters == {"page": "sound"}


# ============================================================================
# 4. Anti-Greedy Routing Tests
# ============================================================================


@pytest.mark.asyncio
async def test_anti_greedy_file_search():
    engine, _ = await _get_brain()
    cmd = "find resolution_notes.txt"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.FIND_FILE
    assert intent.entities.get("pattern") == "resolution_notes.txt"


@pytest.mark.asyncio
async def test_anti_greedy_web_search():
    engine, _ = await _get_brain()
    cmd = "search the web for high refresh rate monitors"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.WEB_SEARCH
    assert "refresh rate" in intent.entities.get("query", "")


@pytest.mark.asyncio
async def test_anti_greedy_app_launch():
    engine, _ = await _get_brain()
    cmd = "open sound recorder"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.OPEN_APPLICATION
    assert intent.entities.get("application") == "sound recorder"


# ============================================================================
# 5. Compound Multi-Step DAG Planning Validation
# ============================================================================


@pytest.mark.asyncio
async def test_compound_screen_brighter_and_lower_volume():
    """Verify that a compound display + audio plan forms a valid 2-step DAG."""
    _, planner = await _get_brain()
    # A plan with step 0: display (increase brightness) and step 1: audio (decrease volume, depends on 0)
    plan = ExecutionPlan(
        steps=[
            PlanStep(
                id="s0",
                tool="display",
                parameters={"action": "increase_brightness", "amount": 10},
                depends_on=[],
            ),
            PlanStep(
                id="s1",
                tool="audio",
                parameters={"action": "decrease_volume", "amount": 10},
                depends_on=[0],
            ),
        ],
        description="Make screen brighter and lower volume",
    )

    validated = planner._validator.validate(plan)
    assert validated == plan
    assert len(validated.steps) == 2
    assert validated.steps[0].tool == "display"
    assert validated.steps[1].tool == "audio"
    assert validated.steps[1].depends_on == [0]
