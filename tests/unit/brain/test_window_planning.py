"""
Unit tests for Window & Desktop Brain Planning (Phase 5.8-E).

Verifies:
- Deterministic classification and fast-path single-step execution plans for all Window actions:
  * show_desktop ("show desktop", "minimize all windows")
  * restore_all ("restore all", "unminimize all")
  * minimize ("minimize Chrome", "minimize this window")
  * maximize ("maximize Chrome", "maximize this")
  * restore ("restore Notepad")
  * focus ("switch to Chrome", "bring Discord to front", "focus Notepad")
  * snap ("snap Chrome to the left", "snap this window right", "snap Notepad center")
  * close ("close this window", "close Chrome window")
  * list ("what windows are open?", "list open windows")
  * get_active ("what window is this?", "what is the current window?")
- Target extraction:
  * Named applications ("Chrome", "Spotify", "Notepad", "Discord")
  * Contextual pronouns ("this", "this window", "active") normalized to "active"
- Anti-greedy classification boundaries:
  * "open Chrome" -> OPEN_APPLICATION (never window/focus)
  * "launch Spotify" -> OPEN_APPLICATION (never window/focus)
  * "search for Chrome" -> WEB_SEARCH (never window)
  * "open WiFi settings" -> OPEN_SETTINGS (never window)
  * "close Chrome application" -> CLOSE_APPLICATION (never window/close)
  * "close Chrome" -> CLOSE_APPLICATION (never window/close)
  * "close Chrome window" -> WINDOW/close
- Compound command handling:
  * "open Notepad and snap it to the left" detected as compound and routed to LLM planner
"""

import pytest
from unittest.mock import AsyncMock, patch

from nova.brain.engine import BrainEngine
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import RecognizedInput
from nova.brain.planner import Planner, get_planner
from nova.brain.types import ConfidenceLevel, IntentCategory
from nova.skills.registry import registry
from nova.skills.system.window import WindowSkill


async def _get_brain():
    engine = BrainEngine()
    await engine.initialize()
    planner = get_planner()
    await planner.initialize()
    return engine, planner


# ============================================================================
# 1. Deterministic Fast Paths for Window Actions
# ============================================================================

@pytest.mark.asyncio
async def test_show_desktop_fast_path():
    engine, planner = await _get_brain()
    for cmd in ("show desktop", "minimize all windows", "minimize everything"):
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.WINDOW
        assert intent.entities.get("action") == "show_desktop"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "window"
        assert plan.steps[0].parameters == {"action": "show_desktop"}


@pytest.mark.asyncio
async def test_restore_all_fast_path():
    engine, planner = await _get_brain()
    for cmd in ("restore all", "restore all windows", "unminimize all"):
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.WINDOW
        assert intent.entities.get("action") == "restore_all"
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "window"
        assert plan.steps[0].parameters == {"action": "restore_all"}


@pytest.mark.asyncio
async def test_minimize_fast_path():
    engine, planner = await _get_brain()
    # Explicit app target
    cmd = "minimize Chrome"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.WINDOW
    assert intent.entities.get("action") == "minimize"
    assert intent.entities.get("target") == "chrome"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "window"
    assert plan.steps[0].parameters == {"action": "minimize", "target": "chrome"}

    # Active / this window target
    cmd_this = "minimize this window"
    intent_this = await engine._intent_classifier.classify(RecognizedInput(text=cmd_this))
    assert intent_this.category == IntentCategory.WINDOW
    assert intent_this.entities.get("action") == "minimize"
    assert intent_this.entities.get("target") == "active"

    plan_this = await planner.plan(cmd_this, intent_this)
    assert plan_this.steps[0].parameters == {"action": "minimize", "target": "active"}


@pytest.mark.asyncio
async def test_maximize_fast_path():
    engine, planner = await _get_brain()
    cmd = "maximize Chrome"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.WINDOW
    assert intent.entities.get("action") == "maximize"
    assert intent.entities.get("target") == "chrome"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "window"
    assert plan.steps[0].parameters == {"action": "maximize", "target": "chrome"}


@pytest.mark.asyncio
async def test_restore_fast_path():
    engine, planner = await _get_brain()
    cmd = "restore Notepad"
    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.category == IntentCategory.WINDOW
    assert intent.entities.get("action") == "restore"
    assert intent.entities.get("target") == "notepad"
    assert planner._is_deterministic_safe(cmd, intent, None) is True

    plan = await planner.plan(cmd, intent)
    assert len(plan.steps) == 1
    assert plan.steps[0].tool == "window"
    assert plan.steps[0].parameters == {"action": "restore", "target": "notepad"}


@pytest.mark.asyncio
async def test_focus_switch_fast_path():
    engine, planner = await _get_brain()

    # "switch to Chrome"
    cmd1 = "switch to Chrome"
    intent1 = await engine._intent_classifier.classify(RecognizedInput(text=cmd1))
    assert intent1.category == IntentCategory.WINDOW
    assert intent1.entities.get("action") == "focus"
    assert intent1.entities.get("target") == "chrome"
    plan1 = await planner.plan(cmd1, intent1)
    assert plan1.steps[0].parameters == {"action": "focus", "target": "chrome"}

    # "bring Discord to front"
    cmd2 = "bring Discord to front"
    intent2 = await engine._intent_classifier.classify(RecognizedInput(text=cmd2))
    assert intent2.category == IntentCategory.WINDOW
    assert intent2.entities.get("action") == "focus"
    assert intent2.entities.get("target") == "discord"
    plan2 = await planner.plan(cmd2, intent2)
    assert plan2.steps[0].parameters == {"action": "focus", "target": "discord"}

    # "focus Notepad"
    cmd3 = "focus Notepad"
    intent3 = await engine._intent_classifier.classify(RecognizedInput(text=cmd3))
    assert intent3.category == IntentCategory.WINDOW
    assert intent3.entities.get("action") == "focus"
    assert intent3.entities.get("target") == "notepad"
    plan3 = await planner.plan(cmd3, intent3)
    assert plan3.steps[0].parameters == {"action": "focus", "target": "notepad"}


@pytest.mark.asyncio
async def test_snap_positions_fast_path():
    engine, planner = await _get_brain()

    cases = [
        ("snap Chrome to the left", "chrome", "left"),
        ("snap this window right", "active", "right"),
        ("snap Notepad top", "notepad", "top"),
        ("snap Spotify to bottom", "spotify", "bottom"),
        ("snap window center", "active", "center"),
    ]
    for cmd, expected_target, expected_pos in cases:
        intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
        assert intent.category == IntentCategory.WINDOW
        assert intent.entities.get("action") == "snap"
        assert intent.entities.get("position") == expected_pos
        assert intent.entities.get("target") == expected_target
        assert planner._is_deterministic_safe(cmd, intent, None) is True

        plan = await planner.plan(cmd, intent)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "window"
        assert plan.steps[0].parameters == {
            "action": "snap",
            "position": expected_pos,
            "target": expected_target,
        }


@pytest.mark.asyncio
async def test_close_window_fast_path():
    engine, planner = await _get_brain()

    # "close this window"
    cmd1 = "close this window"
    intent1 = await engine._intent_classifier.classify(RecognizedInput(text=cmd1))
    assert intent1.category == IntentCategory.WINDOW
    assert intent1.entities.get("action") == "close"
    assert intent1.entities.get("target") == "active"
    plan1 = await planner.plan(cmd1, intent1)
    assert plan1.steps[0].parameters == {"action": "close", "target": "active"}

    # "close Chrome window"
    cmd2 = "close Chrome window"
    intent2 = await engine._intent_classifier.classify(RecognizedInput(text=cmd2))
    assert intent2.category == IntentCategory.WINDOW
    assert intent2.entities.get("action") == "close"
    assert intent2.entities.get("target") == "chrome"
    plan2 = await planner.plan(cmd2, intent2)
    assert plan2.steps[0].parameters == {"action": "close", "target": "chrome"}


@pytest.mark.asyncio
async def test_list_and_active_queries():
    engine, planner = await _get_brain()

    # "what windows are open?"
    cmd_list = "what windows are open?"
    intent_list = await engine._intent_classifier.classify(RecognizedInput(text=cmd_list))
    assert intent_list.category == IntentCategory.WINDOW
    assert intent_list.entities.get("action") == "list"
    plan_list = await planner.plan(cmd_list, intent_list)
    assert plan_list.steps[0].parameters == {"action": "list"}

    # "what window is this?"
    cmd_act = "what window is this?"
    intent_act = await engine._intent_classifier.classify(RecognizedInput(text=cmd_act))
    assert intent_act.category == IntentCategory.WINDOW
    assert intent_act.entities.get("action") == "get_active"
    plan_act = await planner.plan(cmd_act, intent_act)
    assert plan_act.steps[0].parameters == {"action": "get_active"}


# ============================================================================
# 2. Anti-Greedy Classification Protections
# ============================================================================

@pytest.mark.asyncio
async def test_anti_greedy_open_vs_focus():
    engine, _ = await _get_brain()

    # "open Chrome" must stay open_application, NOT window/focus
    intent_open = await engine._intent_classifier.classify(RecognizedInput(text="open Chrome"))
    assert intent_open.category == IntentCategory.OPEN_APPLICATION
    assert intent_open.entities.get("application") == "chrome"

    # "launch Spotify" must stay open_application
    intent_launch = await engine._intent_classifier.classify(RecognizedInput(text="launch Spotify"))
    assert intent_launch.category == IntentCategory.OPEN_APPLICATION
    assert intent_launch.entities.get("application") == "spotify"

    # "switch to Chrome" is window focus
    intent_switch = await engine._intent_classifier.classify(RecognizedInput(text="switch to Chrome"))
    assert intent_switch.category == IntentCategory.WINDOW
    assert intent_switch.entities.get("action") == "focus"


@pytest.mark.asyncio
async def test_anti_greedy_search():
    engine, _ = await _get_brain()
    intent = await engine._intent_classifier.classify(RecognizedInput(text="search for Chrome"))
    assert intent.category == IntentCategory.WEB_SEARCH


@pytest.mark.asyncio
async def test_anti_greedy_settings():
    engine, _ = await _get_brain()
    intent = await engine._intent_classifier.classify(RecognizedInput(text="open WiFi settings"))
    assert intent.category == IntentCategory.OPEN_SETTINGS


@pytest.mark.asyncio
async def test_anti_greedy_close_application_vs_window():
    engine, _ = await _get_brain()

    # "close Chrome application" must remain close_application
    intent_app = await engine._intent_classifier.classify(RecognizedInput(text="close Chrome application"))
    assert intent_app.category == IntentCategory.CLOSE_APPLICATION
    assert intent_app.entities.get("application") == "chrome"

    # "close Chrome" must remain close_application
    intent_plain = await engine._intent_classifier.classify(RecognizedInput(text="close Chrome"))
    assert intent_plain.category == IntentCategory.CLOSE_APPLICATION
    assert intent_plain.entities.get("application") == "chrome"

    # "close Chrome window" is window close
    intent_win = await engine._intent_classifier.classify(RecognizedInput(text="close Chrome window"))
    assert intent_win.category == IntentCategory.WINDOW
    assert intent_win.entities.get("action") == "close"
    assert intent_win.entities.get("target") == "chrome"


# ============================================================================
# 3. Compound Command Planning
# ============================================================================

@pytest.mark.asyncio
async def test_compound_open_and_snap():
    engine, planner = await _get_brain()
    cmd = "open Notepad and snap it to the left"

    intent = await engine._intent_classifier.classify(RecognizedInput(text=cmd))
    assert intent.entities.get("is_compound") is True
    # Must NOT take the single-step fast path
    assert planner._is_deterministic_safe(cmd, intent, None) is False

    # Simulate LLM producing compound plan DAG
    mock_llm_response = (
        '{"steps": ['
        '{"tool": "open_application", "parameters": {"application": "notepad"}, "depends_on": []}, '
        '{"tool": "window", "parameters": {"action": "snap", "position": "left", "target": "notepad"}, "depends_on": [0]}'
        '], "description": "Open Notepad and snap left"}'
    )

    with patch.object(planner._llm_manager, "process", new_callable=AsyncMock) as mock_process:
        mock_process.return_value = mock_llm_response
        plan = await planner.plan(cmd, intent)

        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters == {"application": "notepad"}
        assert plan.steps[0].depends_on == []

        assert plan.steps[1].tool == "window"
        assert plan.steps[1].parameters == {"action": "snap", "position": "left", "target": "notepad"}
        assert plan.steps[1].depends_on == [0]
