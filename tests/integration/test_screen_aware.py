"""
Integration test for screen-aware assistant flow.
"""
import sys
sys.path.insert(0, 'src')

import pytest
from unittest.mock import AsyncMock, patch, Mock

import nova.skills  # ensure skill registration side-effects
from nova.brain.engine import BrainEngine
from nova.screen.elements import ScreenContext
from nova.llm.manager import ExecutionResponse
from nova.skills.registry import registry

# Capture real skills before any test clears the registry
_REAL_SKILLS = dict(registry._skills)


async def _make_brain_engine():
    engine = BrainEngine()
    await engine.initialize()
    return engine


class TestScreenAwareIntegration:
    @pytest.mark.asyncio
    async def test_screen_read_flow(self):
        # Restore real skills in case registry was cleared by other tests
        registry._skills.clear()
        registry._skills.update(_REAL_SKILLS)

        engine = await _make_brain_engine()
        # Get the ScreenSkill instance from the registry AFTER engine is initialized
        screen_skill = registry.get("screen.read")
        print("DEBUG registry keys:", list(registry._skills.keys()))
        print("DEBUG screen_skill:", screen_skill)
        
        # Mock ScreenReader.read_active_screen on the skill's ScreenReader instance
        mock_context = ScreenContext(
            application="chrome.exe",
            window_title="Example - Google Chrome",
            visible_text=["Hello world", "Some text"],
        )
        
        # Create a mock ScreenReader with the mocked method
        mock_screen_reader = Mock()
        mock_screen_reader.read_active_screen.return_value = mock_context
        
        # Patch the skill's _get_screen_reader to return our mock
        with patch.object(screen_skill, '_get_screen_reader', return_value=mock_screen_reader):
            # Mock LLMManager.process to return a summary
            mock_resp = ExecutionResponse(
                requires_execution=False,
                response_text="You are viewing a Chrome window showing Hello world.",
                actions=[],
                provider="placeholder",
                latency_ms=0,
            )
            with patch("nova.llm.manager.LLMManager.process", new_callable=AsyncMock, return_value=mock_resp) as mock_llm:
                resp = await engine.process_text("what's on my screen?")

        assert resp.response_text is not None
        assert "Chrome" in resp.response_text or "Hello" in resp.response_text

    @pytest.mark.asyncio
    async def test_normal_command_no_screen(self):
        engine = await _make_brain_engine()
        with patch("nova.screen.reader.ScreenReader.read_active_screen", new_callable=Mock) as mock_read:
            resp = await engine.process_text("open Chrome")
            mock_read.assert_not_called()
            assert isinstance(resp.response_text, str)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])