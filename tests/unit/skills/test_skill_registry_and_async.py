"""Unit tests for SkillRegistry multi-skill registration and async skill execution."""
import pytest
import asyncio
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import SkillRegistry
from nova.skills.manager import SkillManager
from nova.skills.browser.chrome import ChromeSkill
from nova.skills.browser.edge import EdgeSkill


class MockSyncSkill(BaseSkill):
    intent = "test_sync"

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "test_sync"

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        return {"status": "ok", "detail": "sync skill executed"}


class MockAsyncSkill(BaseSkill):
    intent = "test_async"

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "test_async"

    async def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        await asyncio.sleep(0.01)
        return {"status": "ok", "detail": "async skill executed"}


def test_registry_browser_selection_chrome_and_edge():
    """Chrome and Edge register same intent without overwriting; selection is deterministic."""
    reg = SkillRegistry()
    chrome = ChromeSkill()
    edge = EdgeSkill()

    reg.register(chrome)
    reg.register(edge)

    # Verify both are registered for open_browser
    candidates = reg.get_all_for_intent("open_browser")
    assert len(candidates) == 2
    assert chrome in candidates
    assert edge in candidates

    # Select Chrome
    selected_chrome = reg.get("open_browser", {"intent": "open_browser", "browser": "chrome"})
    assert isinstance(selected_chrome, ChromeSkill)

    # Select Edge
    selected_edge = reg.get("open_browser", {"intent": "open_browser", "browser": "edge"})
    assert isinstance(selected_edge, EdgeSkill)

    # Unknown browser
    selected_unknown = reg.get("open_browser", {"intent": "open_browser", "browser": "firefox"})
    assert selected_unknown is None


def test_registry_duplicate_registration_explicit():
    """Duplicate registration of the exact same skill instance is deduplicated."""
    reg = SkillRegistry()
    chrome = ChromeSkill()
    reg.register(chrome)
    reg.register(chrome)

    assert len(reg.get_all_for_intent("open_browser")) == 1


@pytest.mark.asyncio
async def test_async_skill_execution_contract():
    """SkillManager.execute_intent_async cleanly awaits async skills."""
    manager = SkillManager()
    reg = SkillRegistry()
    async_skill = MockAsyncSkill()
    reg.register(async_skill)
    manager._registry = reg

    result = await manager.execute_intent_async({"intent": "test_async"})
    assert result["status"] == "ok"
    assert result["result"]["detail"] == "async skill executed"
    assert not asyncio.iscoroutine(result["result"])


@pytest.mark.asyncio
async def test_sync_skill_execution_contract_async_caller():
    """SkillManager.execute_intent_async cleanly executes synchronous skills."""
    manager = SkillManager()
    reg = SkillRegistry()
    sync_skill = MockSyncSkill()
    reg.register(sync_skill)
    manager._registry = reg

    result = await manager.execute_intent_async({"intent": "test_sync"})
    assert result["status"] == "ok"
    assert result["result"]["detail"] == "sync skill executed"


def test_sync_skill_execution_sync_caller():
    """SkillManager.execute_intent works for synchronous skills."""
    manager = SkillManager()
    reg = SkillRegistry()
    sync_skill = MockSyncSkill()
    reg.register(sync_skill)
    manager._registry = reg

    result = manager.execute_intent({"intent": "test_sync"})
    assert result["status"] == "ok"
    assert result["result"]["detail"] == "sync skill executed"


@pytest.mark.asyncio
async def test_async_skill_in_sync_caller_in_active_loop_succeeds_via_fallback():
    """SkillManager.execute_intent safely executes async skill from inside active event loop via worker thread."""
    manager = SkillManager()
    reg = SkillRegistry()
    async_skill = MockAsyncSkill()
    reg.register(async_skill)
    manager._registry = reg

    result = manager.execute_intent({"intent": "test_async"})
    assert result["status"] == "ok"
    assert result["result"]["detail"] == "async skill executed"
