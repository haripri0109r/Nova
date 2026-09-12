"""Unit tests for BrainEngine and Application async brain integration."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nova.brain.engine import BrainEngine
from nova.brain.models import BrainResponse, ExecutionPlan, RoutingDecision, IntentResult
from nova.brain.types import IntentCategory, ConfidenceLevel
from nova.application.application import NovaApplication


@pytest.mark.asyncio
async def test_brain_engine_process_text_flow():
    """Verify BrainEngine.process_text() runs end-to-end through planner and agent."""
    engine = BrainEngine()
    
    mock_intent = IntentResult(
        category=IntentCategory.GENERAL_CONVERSATION,
        confidence=0.95,
        confidence_level=ConfidenceLevel.HIGH,
    )
    mock_classifier = AsyncMock()
    mock_classifier.classify = AsyncMock(return_value=mock_intent)
    mock_classifier.initialize = AsyncMock(return_value=True)
    mock_classifier.cleanup = AsyncMock()
    
    mock_orchestrator = AsyncMock()
    mock_orchestrator.initialize = AsyncMock(return_value=True)
    mock_exec_result = MagicMock()
    mock_exec_result.success = True
    mock_exec_result.message = "All steps executed"
    mock_exec_result.results = []
    mock_orchestrator.execute_with_context = AsyncMock(return_value=mock_exec_result)
    
    mock_planner = AsyncMock()
    mock_planner.initialize = AsyncMock(return_value=True)
    mock_plan = MagicMock()
    mock_plan.steps = []
    mock_plan.description = "Test plan"
    mock_planner.plan = AsyncMock(return_value=mock_plan)
    
    engine._initialized = True
    engine._intent_classifier = mock_classifier
    engine._orchestrator = mock_orchestrator
    engine._skill_manager = MagicMock()
    engine._event_bus = MagicMock()
    
    with patch("nova.brain.engine.get_planner", return_value=mock_planner):
        response = await engine.process_text("hello there")
    
    assert isinstance(response, BrainResponse)
    assert response.metadata.get("success") is True
    assert "Done" in response.response_text or "All steps" in response.response_text


@pytest.mark.asyncio
async def test_application_async_calls_process_text():
    """Verify NovaApplication._process_command calls await brain.process_text()."""
    app = NovaApplication()
    
    mock_bus = AsyncMock()
    mock_bus.publish = AsyncMock()
    app._event_bus = mock_bus
    
    mock_brain = MagicMock()
    expected_resp = BrainResponse(
        intent=IntentResult(
            category=IntentCategory.GENERAL_CONVERSATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
        ),
        plan=ExecutionPlan(steps=[]),
        routing=RoutingDecision(target="test", reason="test"),
        response_text="Hello, how can I help?",
        metadata={"success": True},
    )
    mock_brain.process_text = AsyncMock(return_value=expected_resp)
    app._brain = mock_brain
    
    result = await app._process_command("hello nova")
    
    mock_brain.process_text.assert_awaited_once_with("hello nova")
    assert result["status"] == "completed"
    assert result["message"] == "Hello, how can I help?"
