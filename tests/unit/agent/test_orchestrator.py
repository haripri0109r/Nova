"""
Unit tests for Agent Orchestrator.
"""
import sys
from unittest.mock import Mock, MagicMock

# Mock llama_cpp before importing any module that uses it
sys.modules['llama_cpp'] = MagicMock()
sys.modules['llama_cpp'].Llama = MagicMock

import pytest
from unittest.mock import AsyncMock
from typing import Dict, Any

from nova.agent import AgentOrchestrator, PlanExecutor
from nova.intent.schema import Intent, VolumeIntent, BrightnessIntent, AppIntent
from nova.brain.schemas import Plan, IntentParameters
from nova.events.events import IntentResolvedEvent, GoalCompletedEvent


class TestAgentOrchestrator:
    """Tests for AgentOrchestrator."""

    @pytest.fixture
    def mock_intent_engine(self):
        """Mock intent engine."""
        engine = Mock()
        return engine

    @pytest.fixture
    def mock_skill_manager(self):
        """Mock skill manager."""
        mgr = Mock()
        mgr.execute_intent = Mock(return_value={"status": "ok", "result": {"detail": "success"}, "skill": "TestSkill"})
        return mgr

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        bus = Mock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def orchestrator(self, mock_intent_engine, mock_skill_manager, mock_event_bus):
        """Create orchestrator with mocked dependencies."""
        return AgentOrchestrator(
            intent_engine=mock_intent_engine,
            skill_manager=mock_skill_manager,
            event_bus=mock_event_bus,
        )

    def test_run_single_intent_success(self, orchestrator, mock_intent_engine, mock_skill_manager, mock_event_bus):
        """Test successful execution of a single intent."""
        # Setup - use VolumeIntent from intent.schema
        intent = VolumeIntent(
            intent="set_volume",
            action="decrease",
            confidence=0.95,
            amount="small",
        )
        mock_intent_engine.parse.return_value = intent
        mock_skill_manager.execute_intent.return_value = {
            "status": "ok",
            "result": {"detail": "Volume decreased to 80%"},
            "skill": "VolumeSkill",
        }

        # Execute
        result = orchestrator.run("Turn down the volume")

        # Assert
        assert result["status"] == "completed"
        assert result["result"]["detail"] == "Volume decreased to 80%"
        assert result["skill"] == "VolumeSkill"
        assert result["intent"] == "set_volume"
        mock_event_bus.publish.assert_called()

    def test_run_single_intent_low_confidence(self, orchestrator, mock_intent_engine, mock_event_bus):
        """Test clarification request for low confidence intent."""
        # Setup
        intent = VolumeIntent(
            intent="set_volume",
            action="decrease",
            confidence=0.5,  # Below threshold
            amount="small",
        )
        mock_intent_engine.parse.return_value = intent

        # Execute
        result = orchestrator.run("Turn down the volume")

        # Assert
        assert result["status"] == "clarify"
        assert "rephrase" in result["message"].lower()
        assert result["confidence"] == 0.5

    def test_run_plan_execution(self, orchestrator, mock_intent_engine, mock_skill_manager, mock_event_bus):
        """Test execution of a multi-intent plan."""
        # Setup - use the new unified Intent model (VolumeIntent, BrightnessIntent) with domain/operation fields
        intent1 = VolumeIntent(
            intent="set_volume",
            action="set",
            confidence=0.95,
            level=50,
        )
        intent2 = BrightnessIntent(
            intent="set_brightness",
            action="set",
            confidence=0.95,
            level=80,
        )
        from nova.brain.schemas import Plan
        plan = Plan(intents=[intent1, intent2], description="Set volume and brightness")
        mock_intent_engine.parse.return_value = plan
        # Mock skill manager to handle the intent names generated from domain_operation
        def mock_execute_intent(intent_data):
            intent_name = intent_data.get("intent", "")
            if intent_name in ("audio_volume", "display_brightness", "set_volume", "set_brightness"):
                return {"status": "ok", "result": {"detail": "success"}, "skill": "TestSkill"}
            return {"status": "not_found", "message": f"No skill for intent {intent_name}"}
        mock_skill_manager.execute_intent.side_effect = mock_execute_intent

        # Execute
        result = orchestrator.run("Set volume to 50 and brightness to 80")

        # Assert
        assert result["status"] == "completed"
        assert len(result["steps"]) == 2
        assert mock_skill_manager.execute_intent.call_count == 2

    def test_run_error_handling(self, orchestrator, mock_intent_engine, mock_skill_manager, mock_event_bus):
        """Test error handling when skill fails."""
        # Setup
        intent = VolumeIntent(
            intent="set_volume",
            action="decrease",
            confidence=0.95,
            amount="small",
        )
        mock_intent_engine.parse.return_value = intent
        mock_skill_manager.execute_intent.return_value = {
            "status": "error",
            "message": "Audio device not found",
        }

        # Execute
        result = orchestrator.run("Turn down the volume")

        # Assert
        assert result["status"] == "error"
        assert "Audio device not found" in result["message"]

    def test_intent_to_dict_conversion(self, orchestrator):
        """Test intent to dict conversion for SkillManager."""
        intent = VolumeIntent(
            intent="set_volume",
            action="set",
            confidence=0.95,
            level=50,
        )
        data = orchestrator._intent_to_dict(intent)
        assert data["intent"] == "set_volume"
        assert data["action"] == "set"
        assert data["confidence"] == 0.95
        assert data["level"] == 50


class TestPlanExecutor:
    """Tests for PlanExecutor."""

    @pytest.fixture
    def mock_skill_manager(self):
        """Mock skill manager."""
        mgr = Mock()
        mgr.execute_intent = Mock(return_value={"status": "ok", "result": {"detail": "success"}, "skill": "TestSkill"})
        return mgr

    @pytest.fixture
    def mock_event_bus(self):
        """Mock event bus."""
        bus = Mock()
        bus.publish = AsyncMock()
        return bus

    @pytest.fixture
    def plan_executor(self, mock_skill_manager, mock_event_bus):
        """Create plan executor with mocked dependencies."""
        return PlanExecutor(skill_manager=mock_skill_manager, event_bus=mock_event_bus)

    def test_execute_plan_success(self, plan_executor, mock_skill_manager, mock_event_bus):
        """Test successful plan execution."""
        intent1 = VolumeIntent(
            intent="set_volume",
            action="set",
            confidence=0.95,
            level=50,
        )
        intent2 = BrightnessIntent(
            intent="set_brightness",
            action="set",
            confidence=0.95,
            level=80,
        )
        from nova.brain.schemas import Plan
        plan = Plan(intents=[intent1, intent2], description="Test plan")

        result = plan_executor.execute(plan, "Set volume and brightness")

        assert result["status"] == "completed"
        assert len(result["steps"]) == 2
        assert mock_skill_manager.execute_intent.call_count == 2

    def test_execute_plan_failure_stops(self, plan_executor, mock_skill_manager, mock_event_bus):
        """Test plan execution stops on first failure."""
        intent1 = VolumeIntent(
            intent="set_volume",
            action="set",
            confidence=0.95,
            level=50,
        )
        intent2 = BrightnessIntent(
            intent="set_brightness",
            action="set",
            confidence=0.95,
            level=80,
        )
        from nova.brain.schemas import Plan
        plan = Plan(intents=[intent1, intent2], description="Test plan")

        mock_skill_manager.execute_intent.side_effect = [
            {"status": "ok", "result": {"detail": "success"}, "skill": "TestSkill"},
            {"status": "error", "message": "Device not found"},
        ]

        result = plan_executor.execute(plan, "Set volume and brightness")

        assert result["status"] == "error"
        assert "Device not found" in result["message"]
        assert result["failed_at_step"] == 2
        assert len(result["steps"]) == 2