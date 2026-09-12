"""Phase A Regression Tests for Fixes #1 through #7."""
import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock

from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import RecognizedInput
from nova.brain.types import IntentCategory
from nova.agent.executor import PlanExecutor
from nova.agent.orchestrator import AgentOrchestrator
from nova.agent.models import ExecutionPlan, ToolAction, ExecutionContext, ExecutionResult
from nova.skills.registry import SkillRegistry
from nova.skills.base import BaseSkill


# ----------------------------------------------------------------------
# Fix 5: Entity Extraction Regressions
# ----------------------------------------------------------------------
@pytest.mark.asyncio
async def test_intent_entity_extraction_open_chrome():
    """'open chrome' extracts application and browser entity as chrome."""
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()

    result = await classifier.classify(RecognizedInput(text="open chrome"))
    assert result.category == IntentCategory.OPEN_APPLICATION
    assert result.entities.get("application") == "chrome"
    assert result.entities.get("browser") == "chrome"


@pytest.mark.asyncio
async def test_intent_entity_extraction_launch_notepad():
    """'launch notepad' extracts application entity as notepad."""
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()

    result = await classifier.classify(RecognizedInput(text="launch notepad"))
    assert result.category == IntentCategory.OPEN_APPLICATION
    assert result.entities.get("application") == "notepad"


@pytest.mark.asyncio
async def test_intent_entity_extraction_reduce_volume():
    """'reduce volume' extracts action=decrease and amount."""
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()

    result = await classifier.classify(RecognizedInput(text="reduce volume"))
    assert result.category == IntentCategory.SET_VOLUME
    assert result.entities.get("action") == "decrease"
    assert "amount" in result.entities


@pytest.mark.asyncio
async def test_intent_entity_extraction_malformed_commands():
    """Malformed commands like 'open' or 'launch' produce controlled entity results without crashing."""
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()

    res1 = await classifier.classify(RecognizedInput(text="open"))
    assert res1.category == IntentCategory.OPEN_APPLICATION
    assert res1.entities == {}

    res2 = await classifier.classify(RecognizedInput(text="launch"))
    assert res2.category == IntentCategory.OPEN_APPLICATION
    assert res2.entities == {}


# ----------------------------------------------------------------------
# Fix 6: PlanExecutor Async Execution and Parameter Unpacking
# ----------------------------------------------------------------------
class ParamCheckSkill(BaseSkill):
    intent = "test_param_skill"

    def can_handle(self, intent_data):
        return intent_data.get("intent") == "test_param_skill"

    def execute(self, intent_data):
        # Verify that top-level parameter unpacking worked
        app = intent_data.get("application")
        if app == "notepad":
            return {"status": "ok", "detail": "notepad verified"}
        return {"status": "error", "message": f"expected notepad, got {app}"}


@pytest.mark.asyncio
async def test_plan_executor_async_parameter_unpacking():
    """PlanExecutor.execute_async unpacks action_params to top level for skills."""
    executor = PlanExecutor()
    reg = SkillRegistry()
    skill = ParamCheckSkill()
    reg.register(skill)
    executor._registry = reg

    plan = ExecutionPlan(steps=[
        ToolAction(tool="test_param_skill", parameters={"application": "notepad"})
    ])

    context = ExecutionContext(session_id="s1", execution_id="e1")
    res = await executor.execute_async_with_context(plan, context)

    assert res.success is True
    assert res.message == "notepad verified"
    assert len(res.results) == 1
    assert res.results[0].success is True


# ----------------------------------------------------------------------
# Fix 7: Orchestrator Failure Truthfulness (No Fake Success)
# ----------------------------------------------------------------------
def test_orchestrator_returns_failure_when_unconfigured():
    """Orchestrator.run returns an honest error dict when dependencies are missing, not fake success."""
    orch = AgentOrchestrator()
    # No intent_engine or skill_manager configured
    result = orch.run("lower volume")

    assert result["status"] == "error"
    assert "not configured" in result["message"]
    # Ensure NO fake mock text is returned
    assert "Volume decreased to 80%" not in str(result)
    assert result["skill"] is None
