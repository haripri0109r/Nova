"""
Test that normal commands do not invoke ScreenReader.
"""
import sys
import asyncio
sys.path.insert(0, 'src')

import pytest
from unittest.mock import patch, Mock, MagicMock

from nova.brain.brain import Brain
from nova.screen.reader import ScreenReader
from nova.events import get_event_bus


class TestNoScreenOnNormalCommand:
    @pytest.fixture
    def brain(self):
        brain = Brain()
        # Replace orchestrator.run with a mock that accepts context kwarg
        brain._orchestrator.run = Mock(return_value={"status":"completed","message":"ok","result":{}})
        # Mock event bus publish to avoid needing a running loop
        bus = get_event_bus()
        bus.publish = Mock()
        return brain

    @pytest.mark.asyncio
    async def test_normal_command_no_screen(self, brain):
        with patch.object(ScreenReader, "read_active_screen", new_callable=Mock) as mock_read:
            result = await asyncio.to_thread(brain.process, "open Chrome")
            mock_read.assert_not_called()
            assert isinstance(result, dict)
            assert "status" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])