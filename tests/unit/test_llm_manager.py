"""Unit tests for LLMManager.process() and PromptBuilder/Parser contracts."""
import pytest
from unittest.mock import AsyncMock, MagicMock

from nova.llm.manager import LLMManager, LLMManagerConfig
from nova.llm.models import ExecutionResponse, LLMResponse, StructuredResponse, ToolAction
from nova.llm.parser import LLMParser


@pytest.mark.asyncio
async def test_llm_manager_process_empty_text():
    """LLMManager.process with empty text returns empty ExecutionResponse without calling provider."""
    manager = LLMManager()
    await manager.initialize()
    
    resp = await manager.process("")
    assert isinstance(resp, ExecutionResponse)
    assert resp.requires_execution is False
    assert resp.response_text == ""


@pytest.mark.asyncio
async def test_llm_manager_process_with_placeholder():
    """LLMManager.process executes successfully end-to-end with placeholder provider."""
    manager = LLMManager()
    await manager.initialize()
    
    resp = await manager.process("open browser", session_id="test_session")
    assert isinstance(resp, ExecutionResponse)
    assert resp.response_text != ""
    assert isinstance(resp.actions, list)


@pytest.mark.asyncio
async def test_llm_manager_process_with_mock_provider():
    """LLMManager.process correctly builds prompt, queries provider, and parses response."""
    manager = LLMManager()
    await manager.initialize()
    
    mock_provider = AsyncMock()
    mock_provider.name = "mock"
    mock_provider.is_ready = True
    mock_provider.generate = AsyncMock(return_value=LLMResponse(
        content='{"requires_execution": true, "response_text": "Opening browser", "actions": [{"tool": "open_browser", "parameters": {"browser": "chrome"}}]}',
        provider="mock",
    ))
    
    manager._providers = {"mock": mock_provider}
    manager._current_provider = "mock"
    
    resp = await manager.process("open chrome", session_id="test_session_2")
    assert isinstance(resp, ExecutionResponse)
    assert resp.requires_execution is True
    assert resp.response_text == "Opening browser"
    assert len(resp.actions) == 1
    assert resp.actions[0].tool == "open_browser"
    assert resp.actions[0].parameters["browser"] == "chrome"


def test_llm_parser_plain_text_fallback():
    """LLMParser gracefully handles non-JSON plain text."""
    parser = LLMParser()
    structured = parser.parse("Here is what I found on the web.")
    assert isinstance(structured, StructuredResponse)
    assert structured.requires_execution is False
    assert structured.response_text == "Here is what I found on the web."
    assert structured.actions == []


def test_llm_parser_steps_json():
    """LLMParser handles plan schema with steps."""
    parser = LLMParser()
    json_str = '{"description": "Multi-step plan", "steps": [{"tool": "open_browser", "parameters": {"url": "https://google.com"}}]}'
    structured = parser.parse(json_str)
    assert structured.requires_execution is True
    assert structured.response_text == "Multi-step plan"
    assert len(structured.actions) == 1
    assert structured.actions[0].tool == "open_browser"
