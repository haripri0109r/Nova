"""
Unit tests for BrainEngine TASK_CONTROL and TASK_QUERY fast-path routing.
Verifies that task control and query commands bypass Planner, LLM, and skill manager,
while normal skill requests continue using the Planner.
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime

from nova.brain.engine import BrainEngine
from nova.brain.models import RecognizedInput, IntentResult, BrainResponse, ExecutionPlan, PlanStep
from nova.brain.types import IntentCategory, ConfidenceLevel
from nova.agent.models import TaskAction, TaskCommand
from nova.agent.task_command_router import TaskCommandResult


@pytest.fixture
def brain_engine():
    engine = BrainEngine()
    engine._intent_classifier = AsyncMock()
    engine._orchestrator = AsyncMock()
    engine._event_bus = MagicMock()
    engine._initialized = True
    return engine


@pytest.mark.asyncio
async def test_brain_fast_path_task_control_bypasses_planner(brain_engine):
    """Verify TASK_CONTROL commands bypass Planner and LLM entirely."""
    mock_intent = IntentResult(
        category=IntentCategory.TASK_CONTROL,
        confidence=1.0,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"action": "pause", "task_id": "task-test-fast"},
    )
    brain_engine._intent_classifier.classify = AsyncMock(return_value=mock_intent)

    mock_router_result = TaskCommandResult(
        success=True,
        action=TaskAction.PAUSE,
        task_id="task-test-fast",
        message="Task 'task-test-fast' pause requested (completing active step...)",
    )

    with patch("nova.brain.engine.get_task_command_router") as mock_get_router, \
         patch("nova.brain.engine.get_planner") as mock_get_planner:

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(return_value=mock_router_result)
        mock_get_router.return_value = mock_router

        resp = await brain_engine.process_text("pause task task-test-fast", session_id="s1")

        # Verify Router was called with expected TaskCommand
        mock_router.route.assert_awaited_once()
        cmd: TaskCommand = mock_router.route.call_args[0][0]
        assert cmd.action == TaskAction.PAUSE
        assert cmd.task_id == "task-test-fast"
        assert cmd.session_id == "s1"

        # Verify Planner was NEVER called
        mock_get_planner.assert_not_called()

        # Verify BrainResponse structure
        assert isinstance(resp, BrainResponse)
        assert resp.routing.target == "task_command_router"
        assert "pause requested" in resp.response_text


@pytest.mark.asyncio
async def test_brain_fast_path_task_query_bypasses_planner(brain_engine):
    """Verify TASK_QUERY commands bypass Planner and LLM entirely."""
    mock_intent = IntentResult(
        category=IntentCategory.TASK_QUERY,
        confidence=1.0,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"action": "status", "task_id": "task-test-query"},
    )
    brain_engine._intent_classifier.classify = AsyncMock(return_value=mock_intent)

    mock_router_result = TaskCommandResult(
        success=True,
        action=TaskAction.STATUS,
        task_id="task-test-query",
        message="Task 'task-test-query' [RUNNING]: 1/2 steps completed",
    )

    with patch("nova.brain.engine.get_task_command_router") as mock_get_router, \
         patch("nova.brain.engine.get_planner") as mock_get_planner:

        mock_router = AsyncMock()
        mock_router.route = AsyncMock(return_value=mock_router_result)
        mock_get_router.return_value = mock_router

        resp = await brain_engine.process_text("task status task-test-query", session_id="s1")

        mock_router.route.assert_awaited_once()
        mock_get_planner.assert_not_called()

        assert resp.routing.target == "task_command_router"
        assert "1/2 steps completed" in resp.response_text


@pytest.mark.asyncio
async def test_brain_normal_tool_intent_uses_planner(brain_engine):
    """Verify normal tool commands (e.g. system control, apps) continue through the Planner."""
    mock_intent = IntentResult(
        category=IntentCategory.SYSTEM_CONTROL,
        confidence=0.95,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"tool": "app_launcher", "action": "open_app"},
    )
    brain_engine._intent_classifier.classify = AsyncMock(return_value=mock_intent)

    mock_plan = ExecutionPlan(
        steps=[PlanStep(tool="app_launcher", parameters={"app_name": "chrome"})],
        description="Open chrome",
    )
    mock_planner = AsyncMock()
    mock_planner.plan = AsyncMock(return_value=mock_plan)
    mock_planner.initialize = AsyncMock()

    mock_orch_result = MagicMock()
    mock_orch_result.success = True
    mock_orch_result.results = []
    mock_orch_result.message = "Launched chrome"

    with patch("nova.brain.engine.get_planner", return_value=mock_planner) as mock_get_planner, \
         patch.object(brain_engine._orchestrator, "execute_with_context", AsyncMock(return_value=mock_orch_result)):

        resp = await brain_engine.process_text("open chrome", session_id="s1")

        # Verify Planner WAS called
        mock_get_planner.assert_called_once()
        mock_planner.plan.assert_awaited_once()
        assert resp.routing.target == "agent_orchestrator"
