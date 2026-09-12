"""
Unit tests for ScreenReadIntent detection.
"""
import sys
sys.path.insert(0, 'src')

import pytest
from unittest.mock import patch, AsyncMock
from nova.intent.engine import LocalIntentEngine
from nova.intent.schema import ScreenReadIntent


class TestScreenReadIntent:
    @pytest.fixture(autouse=True)
    def mock_generate_intent(self):
        # Mock LLMManager.generate_intent to return screen.read for relevant phrases
        async def mock_generate_intent(transcript):
            if "screen" in transcript.lower() or "what's on" in transcript.lower():
                return {"intent": "screen.read", "action": "read", "confidence": 0.95}
            return {"intent": "fallback", "action": "none", "confidence": 0.0}
        with patch("nova.llm.manager.LLMManager.generate_intent", new_callable=AsyncMock, side_effect=mock_generate_intent):
            yield

    def test_intent_classification(self):
        engine = LocalIntentEngine()
        intent = engine.parse("what's on my screen?")
        assert intent.intent == "screen.read"
        assert intent.action.value == "read"
        assert intent.confidence > 0.75

    def test_variations(self):
        engine = LocalIntentEngine()
        for phrase in [
            "what's on my screen",
            "what is on my screen",
            "describe my screen",
            "read my screen",
        ]:
            intent = engine.parse(phrase)
            assert intent.intent == "screen.read", f"Failed for phrase: {phrase}"
            assert intent.confidence > 0.75


if __name__ == "__main__":
    pytest.main([__file__, "-v"])