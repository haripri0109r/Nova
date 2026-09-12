"""
Unit tests for the Planner.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from unittest.mock import AsyncMock, patch, MagicMock
from nova.brain.planner import Planner
from nova.brain.models import IntentResult, ExecutionPlan, PlanStep
from nova.brain.types import IntentCategory, ConfidenceLevel
from nova.skills.registry import registry


class TestPlanner:
    def setup_method(self):
        """Setup for each test."""
        # Reset registry
        registry._skills.clear()

    def teardown_method(self):
        """Teardown for each test."""
        registry._skills.clear()

    @pytest.mark.asyncio
    async def test_single_step_planning(self):
        """Test that single intent creates single-step plan."""
        planner = Planner()
        await planner.initialize()
        
        # Register a mock skill
        from nova.skills.base import BaseSkill
        class MockSkill(BaseSkill):
            intent = "test_tool"
            description = "A test tool"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "test_tool"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "done"}
        
        registry.register(MockSkill())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"application": "Chrome"}
        )
        
        plan = await planner.plan("open Chrome", intent, None)
        
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters == {"application": "Chrome"}
        assert plan.steps[0].depends_on == []

    @pytest.mark.asyncio
    async def test_single_step_planning(self):
        """Test that single intent creates single-step plan."""
        planner = Planner()
        await planner.initialize()
        
        # Register a mock skill
        from nova.skills.base import BaseSkill
        class MockSkill(BaseSkill):
            intent = "test_tool"
            description = "A test tool"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "test_tool"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "done"}
        
        registry.register(MockSkill())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"application": "Chrome"}
        )
        
        plan = await planner.plan("open Chrome", intent, None)
        
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters == {"application": "Chrome"}
        assert plan.steps[0].depends_on == []

    @pytest.mark.asyncio
    async def test_screen_read_single_step(self):
        """Test screen_read intent creates single-step plan with screen.read tool."""
        planner = Planner()
        await planner.initialize()
        
        # Register screen.read skill
        from nova.skills.base import BaseSkill
        class MockScreenSkill(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "screen content"}
        
        registry.register(MockScreenSkill())
        
        intent = IntentResult(
            category=IntentCategory.SCREEN_READ,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={}
        )
        
        plan = await planner.plan("what's on my screen?", intent, None)
        
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "screen.read"

    @pytest.mark.asyncio
    async def test_multi_step_planning(self):
        """Test that LLM-generated multi-step plan is validated."""
        planner = Planner()
        await planner.initialize()
        
        # Register multiple skills
        from nova.skills.base import BaseSkill
        class MockSkill1(BaseSkill):
            intent = "open_application"
            description = "Open app"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "opened"}
        
        class MockSkill2(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "screen content"}
        
        registry.register(MockSkill1())
        registry.register(MockSkill2())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={}
        )
        
        # Mock LLM to return a multi-step plan
        # Provide context to force LLM path (single-step optimization is skipped when context exists)
        mock_llm_response = MagicMock()
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Open Chrome then read screen"
        }'''
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            plan = await planner.plan("open Chrome and read screen", intent, {"previous": "context"})
        
        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[1].tool == "screen.read"
        assert plan.steps[1].depends_on == [0]

    @pytest.mark.asyncio
    async def test_unknown_tool_rejected(self):
        """Test that unknown tools cause plan rejection."""
        planner = Planner()
        await planner.initialize()
        
        # Register only one skill
        from nova.skills.base import BaseSkill
        class MockSkill(BaseSkill):
            intent = "open_application"
            description = "Open app"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "opened"}
        
        registry.register(MockSkill())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={}
        )
        
        # Mock LLM to return a plan with unknown tool
        # Provide context to force LLM path
        mock_llm_response = MagicMock()
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []},
                {"tool": "fake_tool", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Plan with fake tool"
        }'''
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            with pytest.raises(ValueError, match="unknown tool"):
                await planner.plan("open Chrome and do fake thing", intent, {"previous": "context"})

    @pytest.mark.asyncio
    async def test_invalid_dependency_rejected(self):
        """Test that invalid dependencies are rejected."""
        planner = Planner()
        await planner.initialize()
        
        from nova.skills.base import BaseSkill
        class MockSkill(BaseSkill):
            intent = "open_application"
            description = "Open app"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "opened"}
        
        registry.register(MockSkill())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={}
        )
        
        # Provide context to force LLM path
        # Test forward reference
        mock_llm_response = MagicMock()
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": [1]},
                {"tool": "open_application", "parameters": {}, "depends_on": []}
            ],
            "description": "Forward reference"
        }'''
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            with pytest.raises(ValueError, match="forward reference"):
                await planner.plan("test", intent, {"previous": "context"})
        
        # Test self-dependency
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Self dependency"
        }'''
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            with pytest.raises(ValueError, match="not a previous step"):
                await planner.plan("test", intent, {"previous": "context"})
        
        # Test negative dependency
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": [-1]}
            ],
            "description": "Negative dependency"
        }'''
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            with pytest.raises(ValueError, match="negative dependency"):
                await planner.plan("test", intent, {"previous": "context"})
        
        # Test out of bounds dependency
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": [5]}
            ],
            "description": "Out of bounds dependency"
        }'''
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            with pytest.raises(ValueError, match="not a previous step"):
                await planner.plan("test", intent, {"previous": "context"})

    @pytest.mark.asyncio
    async def test_invalid_json_fallback(self):
        """Test that invalid JSON falls back to single step."""
        planner = Planner()
        await planner.initialize()
        
        from nova.skills.base import BaseSkill
        class MockSkill(BaseSkill):
            intent = "open_application"
            description = "Open app"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "opened"}
        
        registry.register(MockSkill())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"application": "Chrome"}
        )
        
        mock_llm_response = MagicMock()
        mock_llm_response.response_text = "not valid json"
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            plan = await planner.plan("open Chrome", intent, None)
        
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"

    @pytest.mark.asyncio
    async def test_empty_plan_fallback(self):
        """Test that empty plan falls back to single step."""
        planner = Planner()
        await planner.initialize()
        
        from nova.skills.base import BaseSkill
        class MockSkill(BaseSkill):
            intent = "open_application"
            description = "Open app"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "opened"}
        
        registry.register(MockSkill())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"application": "Chrome"}
        )
        
        mock_llm_response = MagicMock()
        mock_llm_response.response_text = '{"steps": [], "description": "empty"}'
        
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            plan = await planner.plan("open Chrome", intent, None)
        
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"

    @pytest.mark.asyncio
    async def test_plan_steps_contain_depends_on(self):
        """Test that PlanStep objects preserve depends_on."""
        planner = Planner()
        await planner.initialize()
        
        from nova.skills.base import BaseSkill
        class MockSkill1(BaseSkill):
            intent = "open_application"
            description = "Open app"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "opened"}
        
        class MockSkill2(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "screen content"}
        
        registry.register(MockSkill1())
        registry.register(MockSkill2())
        
        intent = IntentResult(
            category=IntentCategory.OPEN_APPLICATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={}
        )
        
        mock_llm_response = MagicMock()
        mock_llm_response.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Open Chrome then read screen"
        }'''
        
        # Provide context to force LLM path
        with patch.object(planner._llm_manager, 'process', new_callable=AsyncMock, return_value=mock_llm_response):
            plan = await planner.plan("open Chrome and read screen", intent, {"previous": "context"})
        
        assert len(plan.steps) == 2
        assert plan.steps[0].depends_on == []
        assert plan.steps[1].depends_on == [0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])