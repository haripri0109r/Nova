"""
Integration test for multi-step execution.
"""
import pytest
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from unittest.mock import AsyncMock, patch, MagicMock
from nova.brain.engine import BrainEngine
from nova.brain.models import IntentResult, ExecutionPlan, PlanStep
from nova.brain.types import IntentCategory, ConfidenceLevel
from nova.skills.registry import registry
from nova.llm.manager import ExecutionResponse


class TestMultiStepIntegration:
    @pytest.fixture(autouse=True)
    def setup_teardown(self):
        """Setup and teardown for each test."""
        # Save original skills
        original_skills = dict(registry._skills)
        yield
        # Restore original skills
        registry._skills.clear()
        registry._skills.update(original_skills)

    @pytest.mark.asyncio
    async def test_single_step_open_chrome(self):
        """Test that 'open Chrome' creates single step and executes."""
        engine = BrainEngine()
        await engine.initialize()
        
        # Mock the skill
        from nova.skills.base import BaseSkill
        class MockAppSkill(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "Chrome opened"}
        
        registry.register(MockAppSkill())
        
        # Mock LLM to return single-step plan
        mock_llm = MagicMock()
        mock_llm.response_text = '{"steps": [{"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []}], "description": "Open Chrome"}'
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("open Chrome")
        
        assert "Done" in resp.response_text
        assert "Chrome opened" in resp.response_text
        assert len(resp.plan.steps) == 1
        assert resp.plan.steps[0].tool == "open_application"

    @pytest.mark.asyncio
    async def test_single_step_screen_read(self):
        """Test that 'what's on my screen' creates single screen.read step."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        class MockScreenSkill(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "You are viewing Chrome"}
        
        registry.register(MockScreenSkill())
        
        mock_llm = MagicMock()
        mock_llm.response_text = '{"steps": [{"tool": "screen.read", "parameters": {}, "depends_on": []}], "description": "Read screen"}'
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("what's on my screen?")
        
        assert "Done" in resp.response_text
        assert "You are viewing Chrome" in resp.response_text
        assert len(resp.plan.steps) == 1
        assert resp.plan.steps[0].tool == "screen.read"

    @pytest.mark.asyncio
    async def test_multi_step_open_then_read(self):
        """Test multi-step: open application then read screen."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        
        class MockAppSkill(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "Chrome opened"}
        
        class MockScreenSkill(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "You are viewing GitHub in Chrome"}
        
        registry.register(MockAppSkill())
        registry.register(MockScreenSkill())
        
        # Mock LLM to return multi-step plan
        mock_llm = MagicMock()
        mock_llm.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Open Chrome then read screen"
        }'''
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("open Chrome and read the page")
        
        assert "Done" in resp.response_text
        assert "Chrome opened" in resp.response_text
        assert "You are viewing GitHub in Chrome" in resp.response_text
        assert len(resp.plan.steps) == 2
        assert resp.plan.steps[0].tool == "open_application"
        assert resp.plan.steps[1].tool == "screen.read"
        assert resp.plan.steps[1].depends_on == [0]

    @pytest.mark.asyncio
    async def test_execution_stops_on_failure(self):
        """Test that execution stops when a step fails."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        
        class MockAppSkill(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "Chrome opened"}
        
        class MockFailingSkill(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "error", "message": "Screen read failed"}
        
        registry.register(MockAppSkill())
        registry.register(MockFailingSkill())
        
        mock_llm = MagicMock()
        mock_llm.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Open Chrome then read screen"
        }'''
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("open Chrome and read the page")
        
        assert "Sorry" in resp.response_text
        assert "Screen read failed" in resp.response_text
        # Should have only 1 successful result (first step)
        assert resp.plan.steps[0].tool == "open_application"

    @pytest.mark.asyncio
    async def test_context_propagation(self):
        """Test that ExecutionContext is shared between steps."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        context_received = []
        
        class MockSkill1(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                ctx = intent_data.get("_context")
                context_received.append(("step1", id(ctx)))
                return {"status": "ok", "detail": "Step 1 done"}
        
        class MockSkill2(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                ctx = intent_data.get("_context")
                context_received.append(("step2", id(ctx)))
                # Verify we can access step 1's result
                if ctx and ctx.step_results:
                    assert ctx.step_results[0]["tool"] == "open_application"
                return {"status": "ok", "detail": "Step 2 done"}
        
        registry.register(MockSkill1())
        registry.register(MockSkill2())
        
        mock_llm = MagicMock()
        mock_llm.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Two steps"
        }'''
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("test multi step")
        
        assert "Done" in resp.response_text
        # Both steps should receive the SAME context object
        assert len(context_received) == 2
        assert context_received[0][1] == context_received[1][1], "Context object should be identical"

    @pytest.mark.asyncio
    async def test_current_step_tracking(self):
        """Test that current_step is tracked in ExecutionContext."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        current_steps = []
        
        class MockSkill1(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                ctx = intent_data.get("_context")
                current_steps.append(("step1", ctx.current_step if ctx else None))
                return {"status": "ok", "detail": "Step 1 done"}
        
        class MockSkill2(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                ctx = intent_data.get("_context")
                current_steps.append(("step2", ctx.current_step if ctx else None))
                return {"status": "ok", "detail": "Step 2 done"}
        
        registry.register(MockSkill1())
        registry.register(MockSkill2())
        
        mock_llm = MagicMock()
        mock_llm.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Two steps"
        }'''
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("test multi step")
        
        assert "Done" in resp.response_text
        assert current_steps[0] == ("step1", 0), f"Step 1 should have current_step=0, got {current_steps[0]}"
        assert current_steps[1] == ("step2", 1), f"Step 2 should have current_step=1, got {current_steps[1]}"

    @pytest.mark.asyncio
    async def test_result_storage_in_context(self):
        """Test that step results are stored in ExecutionContext."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        
        class MockSkill1(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "Chrome opened", "pid": 1234}
        
        class MockSkill2(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                ctx = intent_data.get("_context")
                # Verify step 1 result is accessible
                assert len(ctx.step_results) == 1
                assert ctx.step_results[0]["tool"] == "open_application"
                assert ctx.step_results[0]["success"] is True
                assert ctx.step_results[0]["result"]["detail"] == "Chrome opened"
                return {"status": "ok", "detail": "Screen read"}
        
        registry.register(MockSkill1())
        registry.register(MockSkill2())
        
        mock_llm = MagicMock()
        mock_llm.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Two steps"
        }'''
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("test multi step")
        
        assert "Done" in resp.response_text

    @pytest.mark.asyncio
    async def test_brain_response_plan_matches_executed(self):
        """Test that BrainResponse.plan matches the executed plan."""
        engine = BrainEngine()
        await engine.initialize()
        
        from nova.skills.base import BaseSkill
        
        class MockSkill1(BaseSkill):
            intent = "open_application"
            description = "Open application"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "open_application"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "Opened"}
        
        class MockSkill2(BaseSkill):
            intent = "screen.read"
            description = "Read screen"
            def can_handle(self, intent_data):
                return intent_data.get("intent") == "screen.read"
            async def execute(self, intent_data):
                return {"status": "ok", "detail": "Screen content"}
        
        registry.register(MockSkill1())
        registry.register(MockSkill2())
        
        mock_llm = MagicMock()
        mock_llm.response_text = '''{
            "steps": [
                {"tool": "open_application", "parameters": {"application": "Chrome"}, "depends_on": []},
                {"tool": "screen.read", "parameters": {}, "depends_on": [0]}
            ],
            "description": "Open Chrome then read"
        }'''
        
        with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_llm):
            resp = await engine.process_text("open Chrome and read")
        
        # Verify BrainResponse.plan matches executed plan
        assert len(resp.plan.steps) == 2
        assert resp.plan.steps[0].tool == "open_application"
        assert resp.plan.steps[0].parameters == {"application": "Chrome"}
        assert resp.plan.steps[0].depends_on == []
        assert resp.plan.steps[1].tool == "screen.read"
        assert resp.plan.steps[1].depends_on == [0]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])