"""
Unit tests for NovaApplication lifecycle.
"""
import sys
import pytest
from unittest.mock import Mock, AsyncMock, MagicMock

# Mock llama_cpp before importing any Nova modules
sys.modules['llama_cpp'] = MagicMock()
sys.modules['llama_cpp'].Llama = MagicMock

# Mock torch and related heavy deps
torch_mock = MagicMock()
torch_mock.__spec__ = MagicMock()
torch_mock.__version__ = "2.0.0"
torch_mock.cuda = MagicMock()
torch_mock.cuda.is_available = MagicMock(return_value=False)
torch_mock.hub = MagicMock()
torch_mock.hub.load = MagicMock(return_value=(MagicMock(), None))
torch_mock.nn = MagicMock()
torch_mock.nn.functional = MagicMock()
torch_mock.optim = MagicMock()
sys.modules["torch"] = torch_mock
sys.modules["torchvision"] = MagicMock()
sys.modules["torchaudio"] = MagicMock()
sys.modules["torch.nn"] = MagicMock()
sys.modules["torch.nn.functional"] = MagicMock()

# Mock other heavy optional deps
sys.modules["cv2"] = MagicMock()
sys.modules["faster_whisper"] = MagicMock()
sys.modules["faster_whisper.transcribe"] = MagicMock()

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from typing import Dict, Any

from nova.application import NovaApplication


@pytest.fixture
def mock_event_bus():
    bus = Mock()
    bus.start = AsyncMock()
    bus.stop = AsyncMock()
    bus.publish = AsyncMock()
    bus._running = True
    return bus


@pytest.fixture
def mock_brain():
    brain = Mock()
    brain.process = Mock(return_value={"status": "completed", "message": "Done."})
    return brain


@pytest.fixture
def mock_intent_engine():
    engine = Mock()
    engine.parse = Mock(return_value=None)
    return engine


@pytest.fixture
def mock_skill_manager():
    mgr = Mock()
    mgr.execute_intent = Mock(return_value={"status": "ok", "result": {"detail": "ok"}, "skill": "TestSkill"})
    return mgr


@pytest.fixture
def mock_llm_manager():
    mgr = Mock()
    mgr.initialize = AsyncMock(return_value=True)
    mgr.generate_intent = Mock(return_value={"intent": "test", "action": "test"})
    return mgr


@pytest.fixture
def mock_wake_listener():
    """Mock WakePhraseListener to avoid loading torch/hub."""
    with patch("nova.wake_phrase.WakePhraseListener", autospec=True) as mock_cls:
        mock_instance = MagicMock()
        mock_instance.listen_for_utterance = Mock(return_value="hello nova")
        mock_cls.return_value = mock_instance
        # Provide static method matches_wake_phrase
        mock_cls.matches_wake_phrase = staticmethod(lambda text: True)
        yield mock_cls


@pytest.fixture
def app(monkeypatch, mock_event_bus, mock_brain, mock_intent_engine, mock_skill_manager, mock_llm_manager, mock_wake_listener):
    """Create NovaApplication with all dependencies mocked using persistent patches."""
    # Patch at the module where functions are USED (nova.application.application)
    monkeypatch.setattr("nova.application.application.get_event_bus", lambda: mock_event_bus)
    monkeypatch.setattr("nova.application.application.get_brain", lambda: mock_brain)
    monkeypatch.setattr("nova.application.application.get_intent_engine", lambda: mock_intent_engine)
    monkeypatch.setattr("nova.application.application.get_skill_manager", lambda: mock_skill_manager)
    monkeypatch.setattr("nova.application.application.get_agent_orchestrator", lambda: Mock())
    # For get_llm_manager, it's imported locally in initialize(), so patch at source
    monkeypatch.setattr("nova.llm.manager.get_llm_manager", lambda: mock_llm_manager)

    # Import inside the patch context to avoid import errors
    from nova.application import NovaApplication
    app = NovaApplication()

    # Ensure internal attributes are the mocks
    app._event_bus = mock_event_bus
    app._brain = mock_brain
    app._intent_engine = mock_intent_engine
    app._skill_manager = mock_skill_manager
    app._llm_manager = mock_llm_manager
    # Also mock the wake listener and its methods
    app._wake_listener = mock_wake_listener.return_value
    # Mock the wake phrase match static method
    from nova.wake_phrase import WakePhraseListener
    WakePhraseListener.matches_wake_phrase = Mock(return_value=True)
    yield app


@pytest.mark.asyncio
async def test_initialize_success(app, mock_event_bus, mock_llm_manager):
    await app.initialize()
    assert app._initialized is True
    mock_event_bus.start.assert_awaited_once()
    mock_llm_manager.initialize.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_sets_running(app):
    await app.start()
    assert app._running is True


@pytest.mark.asyncio
async def test_stop_stops_components(app, mock_event_bus):
    app._running = True
    await app.stop()
    assert app._running is False
    mock_event_bus.stop.assert_awaited_once()


@pytest.mark.asyncio
async def test_health_check_returns_status(app):
    health = app.health_check()
    assert isinstance(health, dict)
    assert "application" in health
    assert "brain" in health
    assert "event_bus" in health
    assert health["application"] == "stopped"


@pytest.mark.asyncio
async def test_startup_failure_llm_manager_fails(app, mock_llm_manager):
    """If LLMManager fails to initialize, initialize should raise."""
    app._initialized = False
    mock_llm_manager.initialize = AsyncMock(return_value=False)
    with pytest.raises(RuntimeError):
        await app.initialize()


@pytest.mark.asyncio
async def test_startup_failure_event_bus_fails(app, mock_event_bus):
    """If EventBus fails to start, initialize should raise."""
    mock_event_bus.start = AsyncMock(side_effect=RuntimeError("bus down"))
    app._initialized = False
    with pytest.raises(RuntimeError):
        await app.initialize()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])