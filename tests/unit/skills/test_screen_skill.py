"""
Unit tests for ScreenSkill.
"""
import sys
import asyncio
sys.path.insert(0, 'src')

import pytest
from unittest.mock import AsyncMock, Mock, patch

from nova.skills.screen.screen_skill import ScreenSkill
from nova.screen.elements import ScreenContext
from nova.llm.manager import ExecutionResponse


class TestScreenSkill:
    @pytest.fixture
    def skill(self):
        return ScreenSkill()

    @pytest.mark.asyncio
    async def test_execute_returns_summary(self, skill):
        # Mock ScreenReader.read_active_screen at class level
        mock_context = ScreenContext(
            application="chrome.exe",
            window_title="Example - Google Chrome",
            visible_text=["Hello world", "Some text"],
        )
        with patch("nova.screen.reader.ScreenReader.read_active_screen", return_value=mock_context) as mock_read:
            # Mock LLMManager.process
            mock_resp = ExecutionResponse(
                requires_execution=False,
                response_text="You are viewing a Chrome window showing Hello world.",
                actions=[],
                provider="placeholder",
                latency_ms=0,
            )
            with patch.object(skill._llm_manager, "process", new_callable=AsyncMock, return_value=mock_resp) as mock_llm:
                result = await skill.execute({"intent": "screen.read"})

        assert result["status"] == "ok"
        assert "detail" in result
        assert "screen" in result["detail"].lower() or "chrome" in result["detail"].lower()
        assert result["skill"] == "ScreenSkill"
        mock_read.assert_called_once()
        mock_llm.assert_called_once()
        # Verify extra_context passed
        call_args = mock_llm.call_args
        assert call_args.kwargs.get("context", {}).get("extra_context") is not None

    @pytest.mark.asyncio
    async def test_execute_handles_llm_failure(self, skill):
        mock_context = ScreenContext(application="notepad.exe", window_title="Untitled - Notepad")
        with patch("nova.screen.reader.ScreenReader.read_active_screen", return_value=mock_context):
            with patch.object(skill._llm_manager, "process", side_effect=Exception("LLM down")):
                result = await skill.execute({"intent": "screen.read"})

        assert result["status"] == "ok"
        assert "error" in result["detail"].lower() or "error" in result["detail"].lower() or "encountered" in result["detail"].lower()

    @pytest.mark.asyncio
    async def test_execute_handles_uia_timeout(self, skill):
        # Simulate UIA timeout by making asyncio.wait_for raise TimeoutError
        with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
            with patch("nova.screen.reader.ScreenReader.read_active_screen", return_value=ScreenContext()):
                result = await skill.execute({"intent": "screen.read"})

        assert result["status"] == "error"
        assert "time" in result["detail"].lower() or "couldn't" in result["detail"].lower()
        assert result["skill"] == "ScreenSkill"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])