"""
Unit tests for Nova Shutdown Precondition Workflow in BrainEngine.

Verifies:
1. Initial shutdown blocked when user applications are open
2. Initial shutdown proceeds to existing HIGH-risk confirmation when no apps are open
3. "done" does not trigger shutdown without pending workflow
4. "done" continues pending shutdown workflow
5. Mandatory second application check is performed
6. Remaining applications block shutdown on second check
7. Shutdown proceeds to confirmation only after all apps are closed
8. Cancellation clears pending shutdown workflow state
9. Session isolation: session A pending state does not affect session B
10. Newly opened application between checks is detected on second check
11. HIGH-risk confirmation remains mandatory (never bypassed)
12. ShutdownSkill remains responsible ONLY for actual shutdown
13. Unrelated request does not trigger shutdown and clears pending workflow
14. Pending workflow expiration clears state after TTL
15. Repeated "shutdown" command while pending re-checks actual state
16. Additional continuation phrases ("all closed", "ready")
17. Additional cancellation phrases ("cancel shutdown", "stop")
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from nova.agent.models import ExecutionContext, ExecutionRequest, ExecutionResult, TaskAction, TaskCommand
from nova.agent.step_risk_policy import get_confirmation_manager, RiskLevel
from nova.brain.engine import BrainEngine
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import BrainResponse, ExecutionPlan, PlanStep, RecognizedInput
from nova.brain.shutdown_workflow import (
    ShutdownWorkflowManager,
    get_shutdown_workflow_manager,
    is_cancellation_phrase,
    is_continuation_phrase,
)
from nova.brain.types import ConfidenceLevel, IntentCategory
from nova.skills.system.shutdown import ShutdownSkill


@pytest.fixture(autouse=True)
def clean_workflow_manager():
    """Ensure clean shutdown workflow manager state before and after each test."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.clear_all()
    yield
    wf_mgr.clear_all()


@pytest.fixture
def mock_brain_engine():
    """Build a test BrainEngine instance with mocked orchestrator, planner, and event bus."""
    engine = BrainEngine()
    engine._intent_classifier = PlaceholderIntentClassifier()
    engine._orchestrator = AsyncMock()
    engine._event_bus = MagicMock()
    engine._initialized = True

    mock_planner = AsyncMock()
    mock_planner.initialize = AsyncMock(return_value=True)

    async def mock_plan(text, intent, context=None):
        tool = intent.category.value if intent else "unknown"
        return ExecutionPlan(
            steps=[PlanStep(tool=tool, parameters={})],
            description=f"Plan {tool}",
        )

    mock_planner.plan = AsyncMock(side_effect=mock_plan)

    with patch("nova.brain.engine.get_planner", return_value=mock_planner):
        yield engine


# ---------------------------------------------------------------------------
# Precondition Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initial_shutdown_blocked_when_apps_open(mock_brain_engine):
    """When user requests shutdown with open apps, shutdown is blocked and apps are listed."""
    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {
            "ready": False,
            "open_applications": ["Google Chrome", "Visual Studio Code"],
            "windows": [],
        }

        resp: BrainResponse = await mock_brain_engine.process_text("shutdown my laptop", session_id="s1")

        assert "Google Chrome and Visual Studio Code are still open" in resp.response_text
        assert "Please close them and tell me when you're ready" in resp.response_text
        # Verify orchestrator was NOT called to execute shutdown
        mock_brain_engine._orchestrator.execute_with_context.assert_not_called()

        # Verify session state is pending
        wf_mgr = get_shutdown_workflow_manager()
        assert wf_mgr.is_pending("s1") is True
        assert wf_mgr.get_pending("s1").open_applications == ["Google Chrome", "Visual Studio Code"]


@pytest.mark.asyncio
async def test_initial_shutdown_proceeds_to_confirmation_when_no_apps(mock_brain_engine):
    """When user requests shutdown with NO open apps, it proceeds directly to high-risk confirmation."""
    mock_brain_engine._orchestrator.execute_with_context.return_value = ExecutionResult(
        success=False,
        message="Confirmation required before executing shutdown.",
        results=[],
    )

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {"ready": True, "open_applications": [], "windows": []}

        resp: BrainResponse = await mock_brain_engine.process_text("shutdown my pc", session_id="s1")

        # Orchestrator was invoked with shutdown execution plan
        mock_brain_engine._orchestrator.execute_with_context.assert_called_once()
        assert "Confirmation required before executing shutdown." in resp.response_text

        # Workflow manager does NOT have pending app closure
        wf_mgr = get_shutdown_workflow_manager()
        assert wf_mgr.is_pending("s1") is False


@pytest.mark.asyncio
async def test_done_does_not_trigger_shutdown_without_pending(mock_brain_engine):
    """Saying 'done' without an active pending shutdown does not trigger shutdown."""
    resp: BrainResponse = await mock_brain_engine.process_text("done", session_id="s1")

    # Intent is general conversation, not shutdown
    assert resp.intent.category == IntentCategory.GENERAL_CONVERSATION
    for call in mock_brain_engine._orchestrator.execute_with_context.call_args_list:
        req: ExecutionRequest = call[0][0]
        for action in req.actions:
            assert action.tool != "shutdown"


@pytest.mark.asyncio
async def test_done_continues_pending_shutdown_workflow(mock_brain_engine):
    """Saying 'done' during an active pending shutdown continues the workflow and re-checks state."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome"])

    mock_brain_engine._orchestrator.execute_with_context.return_value = ExecutionResult(
        success=False,
        message="Confirmation required before executing shutdown.",
        results=[],
    )

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {"ready": True, "open_applications": [], "windows": []}

        resp: BrainResponse = await mock_brain_engine.process_text("done", session_id="s1")

        mock_check.assert_called_once()
        assert wf_mgr.is_pending("s1") is False
        mock_brain_engine._orchestrator.execute_with_context.assert_called_once()
        assert "Confirmation required before executing shutdown." in resp.response_text


@pytest.mark.asyncio
async def test_second_application_check_blocks_if_apps_remain(mock_brain_engine):
    """If user says 'done' but Chrome is still open, shutdown remains blocked."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome", "Spotify"])

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {
            "ready": False,
            "open_applications": ["Google Chrome"],
            "windows": [],
        }

        resp: BrainResponse = await mock_brain_engine.process_text("they are closed", session_id="s1")

        mock_check.assert_called_once()
        assert "Google Chrome is still open" in resp.response_text
        assert "Please close it before I shut down" in resp.response_text
        mock_brain_engine._orchestrator.execute_with_context.assert_not_called()
        assert wf_mgr.is_pending("s1") is True
        assert wf_mgr.get_pending("s1").open_applications == ["Google Chrome"]


@pytest.mark.asyncio
async def test_all_apps_closed_allows_confirmation(mock_brain_engine):
    """When all apps are closed and user says 'all closed', workflow proceeds to confirmation."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Notepad"])

    mock_brain_engine._orchestrator.execute_with_context.return_value = ExecutionResult(
        success=False,
        message="Confirmation required before executing shutdown.",
        results=[],
    )

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {"ready": True, "open_applications": [], "windows": []}

        resp: BrainResponse = await mock_brain_engine.process_text("all closed", session_id="s1")

        assert wf_mgr.is_pending("s1") is False
        mock_brain_engine._orchestrator.execute_with_context.assert_called_once()
        assert "Confirmation required before executing shutdown." in resp.response_text


@pytest.mark.asyncio
async def test_cancellation_clears_pending_shutdown(mock_brain_engine):
    """User saying 'never mind' clears the pending workflow."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome"])

    resp: BrainResponse = await mock_brain_engine.process_text("never mind", session_id="s1")

    assert "Okay, I won't shut down." in resp.response_text
    assert wf_mgr.is_pending("s1") is False
    mock_brain_engine._orchestrator.execute_with_context.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_shutdown_phrase(mock_brain_engine):
    """User saying 'cancel shutdown' clears the pending workflow."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome"])

    resp: BrainResponse = await mock_brain_engine.process_text("cancel shutdown", session_id="s1")

    assert "Okay, I won't shut down." in resp.response_text
    assert wf_mgr.is_pending("s1") is False


@pytest.mark.asyncio
async def test_session_isolation(mock_brain_engine):
    """Pending shutdown in session A does not affect session B."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("session_A", ["Google Chrome"])

    assert wf_mgr.is_pending("session_A") is True
    assert wf_mgr.is_pending("session_B") is False

    # In session B, 'done' is just general conversation
    resp_b: BrainResponse = await mock_brain_engine.process_text("done", session_id="session_B")
    assert resp_b.intent.category == IntentCategory.GENERAL_CONVERSATION
    assert wf_mgr.is_pending("session_A") is True


@pytest.mark.asyncio
async def test_newly_opened_app_detected_on_second_check(mock_brain_engine):
    """If user closes Chrome but opens Notepad before saying done, second check catches it."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome"])

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {
            "ready": False,
            "open_applications": ["Notepad"],
            "windows": [],
        }

        resp: BrainResponse = await mock_brain_engine.process_text("done, shutdown", session_id="s1")

        assert "Notepad is still open. Please close it before I shut down." in resp.response_text
        mock_brain_engine._orchestrator.execute_with_context.assert_not_called()
        assert wf_mgr.get_pending("s1").open_applications == ["Notepad"]


@pytest.mark.asyncio
async def test_high_risk_confirmation_remains_mandatory(mock_brain_engine):
    """Verify that after precondition passes, orchestrator returns high-risk confirmation."""
    mock_brain_engine._orchestrator.execute_with_context.return_value = ExecutionResult(
        success=False,
        message="Confirmation required before executing shutdown.",
        results=[],
    )

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {"ready": True, "open_applications": [], "windows": []}

        resp: BrainResponse = await mock_brain_engine.process_text("shutdown", session_id="s1")

        assert "Confirmation required before executing shutdown." in resp.response_text
        call_args = mock_brain_engine._orchestrator.execute_with_context.call_args[0]
        req: ExecutionRequest = call_args[0]
        assert len(req.actions) == 1
        assert req.actions[0].tool == "shutdown"


@pytest.mark.asyncio
async def test_unrelated_command_clears_pending_shutdown(mock_brain_engine):
    """An unrelated command clears pending shutdown and is processed normally."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome"])

    mock_brain_engine._orchestrator.execute_with_context.return_value = ExecutionResult(
        success=True,
        message="Battery is 90%",
        results=[],
    )

    # User asks something unrelated
    resp: BrainResponse = await mock_brain_engine.process_text("what is my battery?", session_id="s1")

    assert wf_mgr.is_pending("s1") is False
    # Verified that shutdown was not triggered
    for call in mock_brain_engine._orchestrator.execute_with_context.call_args_list:
        req: ExecutionRequest = call[0][0]
        for action in req.actions:
            assert action.tool != "shutdown"


@pytest.mark.asyncio
async def test_pending_workflow_expiration():
    """Pending shutdown state expires after TTL."""
    mgr = ShutdownWorkflowManager(ttl_seconds=1)
    mgr.set_pending("s1", ["Chrome"])
    assert mgr.is_pending("s1") is True

    # Simulate time passing
    with patch("nova.brain.shutdown_workflow.datetime") as mock_dt:
        mock_dt.utcnow.return_value = datetime.utcnow() + timedelta(seconds=2)
        assert mgr.is_pending("s1") is False
        assert mgr.get_pending("s1") is None


@pytest.mark.asyncio
async def test_repeated_shutdown_while_pending_rechecks_state(mock_brain_engine):
    """Repeating 'shutdown' while pending re-checks actual application state."""
    wf_mgr = get_shutdown_workflow_manager()
    wf_mgr.set_pending("s1", ["Google Chrome"])

    mock_brain_engine._orchestrator.execute_with_context.return_value = ExecutionResult(
        success=False,
        message="Confirmation required before executing shutdown.",
        results=[],
    )

    with patch("nova.skills.system.app_detector.check_shutdown_precondition") as mock_check:
        mock_check.return_value = {"ready": True, "open_applications": [], "windows": []}

        resp: BrainResponse = await mock_brain_engine.process_text("shutdown my laptop", session_id="s1")

        mock_check.assert_called_once()
        assert wf_mgr.is_pending("s1") is False
        mock_brain_engine._orchestrator.execute_with_context.assert_called_once()


def test_shutdown_skill_responsibility_unchanged():
    """Verify ShutdownSkill itself remains strictly responsible ONLY for Windows shutdown."""
    skill = ShutdownSkill()
    assert skill.intent == "shutdown"
    assert skill.parameters_schema["required"] == []
    assert skill.parameters_schema["additionalProperties"] is False

    # Does not have app detection or closing methods
    assert not hasattr(skill, "check_precondition")
    assert not hasattr(skill, "close_apps")
    assert not hasattr(skill, "terminate_process")


def test_phrase_helpers():
    """Verify cancellation and continuation phrase detection."""
    # Cancellations
    assert is_cancellation_phrase("cancel") is True
    assert is_cancellation_phrase("cancel shutdown") is True
    assert is_cancellation_phrase("never mind") is True
    assert is_cancellation_phrase("don't shut down") is True
    assert is_cancellation_phrase("dont shut down the pc") is True
    assert is_cancellation_phrase("forget it") is True
    assert is_cancellation_phrase("stop") is True
    assert is_cancellation_phrase("abort") is True

    # Continuations
    assert is_continuation_phrase("done") is True
    assert is_continuation_phrase("done, shutdown") is True
    assert is_continuation_phrase("done shutdown") is True
    assert is_continuation_phrase("all closed") is True
    assert is_continuation_phrase("they're closed") is True
    assert is_continuation_phrase("they are closed") is True
    assert is_continuation_phrase("ready") is True
    assert is_continuation_phrase("i'm ready") is True
    assert is_continuation_phrase("okay shutdown") is True
    assert is_continuation_phrase("ok shutdown") is True
    assert is_continuation_phrase("shut down now") is True
    assert is_continuation_phrase("now shut it down") is True

    # Non-continuations
    assert is_continuation_phrase("what is the weather?") is False
    assert is_continuation_phrase("open chrome") is False
    assert is_continuation_phrase("confirm shutdown 123456") is False
