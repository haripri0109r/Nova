"""
Unit tests for Phase 5.4C-A — Fix P1 Routing + Establish Canonical Skill Schema.

Verifies:
A. Simple deterministic: open chrome
B. Simple deterministic: launch notepad
C. Simple deterministic: reduce volume
D. Compound with conjunction: open chrome and search youtube for spider man
E. Compound without conjunction: open chrome search youtube for spider man
F. Compound: launch terminal run pytest
G. Compound: start edge navigate to github
H. Normal multi-word application: open visual studio code (remains deterministic)
I. Parameter validation: open_application with missing/invalid parameters
J. Unknown tool rejection
K. Valid multi-step plan passes validation
L. Invalid multi-step plan fails validation truthfully
M. Schema retrieval from SkillRegistry
N. Tool definition generation from registered schema
CRITICAL: 'open chrome search youtube for spider man' NEVER produces
          open_application(application="chrome search youtube for spider man")
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nova.brain.compound import is_compound_command, extract_clean_application_target
from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.models import RecognizedInput, IntentResult, ExecutionPlan, PlanStep
from nova.brain.types import IntentCategory, ConfidenceLevel
from nova.brain.planner import Planner
from nova.brain.validator import PlanValidator
from nova.brain.exceptions import PlanValidationError, PlanningError
from nova.skills.registry import registry
from nova.skills.base import BaseSkill
from nova.skills.applications.launcher import AppLauncherSkill
from nova.skills.applications.closer import AppCloserSkill
from nova.skills.browser.chrome import ChromeSkill
from nova.skills.browser.edge import EdgeSkill
from nova.skills.browser.search import SearchSkill
from nova.skills.system.volume import VolumeSkill


@pytest.fixture(autouse=True)
def setup_compound_routing_environment():
    """Ensure core skills are registered in registry for compound routing tests."""
    saved_skills = dict(registry._skills)
    saved_by_intent = {k: list(v) for k, v in registry._skills_by_intent.items()}
    registry._skills.clear()
    registry.register(AppLauncherSkill())
    registry.register(AppCloserSkill())
    registry.register(ChromeSkill())
    registry.register(EdgeSkill())
    registry.register(SearchSkill())
    registry.register(VolumeSkill())
    yield
    registry._skills.clear()
    registry._skills.update(saved_skills)
    registry._skills_by_intent.clear()
    registry._skills_by_intent.update(saved_by_intent)


# ======================================================================
# 1. Compound Detection & Entity Extraction Unit Tests
# ======================================================================

def test_compound_detection_conjunction():
    assert is_compound_command("open chrome and search youtube for spider man") is True
    assert is_compound_command("open chrome then search youtube") is True
    assert is_compound_command("open notepad and type hello") is True


def test_compound_detection_without_conjunction():
    assert is_compound_command("open chrome search youtube for spider man") is True
    assert is_compound_command("launch terminal run pytest") is True
    assert is_compound_command("start edge navigate to github") is True
    assert is_compound_command("open notepad type hello") is True


def test_compound_detection_multi_word_apps_not_compound():
    assert is_compound_command("open visual studio code") is False
    assert is_compound_command("open google chrome") is False
    assert is_compound_command("launch task manager") is False
    assert is_compound_command("run android studio") is False
    assert is_compound_command("open file explorer") is False
    assert is_compound_command("launch notepad") is False
    assert is_compound_command("reduce volume") is False


def test_extract_clean_application_target_prevents_greedy_capture():
    # Case with conjunction
    app, is_comp = extract_clean_application_target("chrome and search youtube for spider man")
    assert app == "chrome"
    assert is_comp is True

    # Case without conjunction (CRITICAL TEST)
    app, is_comp = extract_clean_application_target("chrome search youtube for spider man")
    assert app == "chrome"
    assert is_comp is True
    assert app != "chrome search youtube for spider man"

    # Secondary verbs
    app, is_comp = extract_clean_application_target("terminal run pytest")
    assert app == "terminal"
    assert is_comp is True

    app, is_comp = extract_clean_application_target("edge navigate to github")
    assert app == "edge"
    assert is_comp is True

    # Multi-word apps (not compound)
    app, is_comp = extract_clean_application_target("visual studio code")
    assert app == "visual studio code"
    assert is_comp is False

    app, is_comp = extract_clean_application_target("google chrome")
    assert app == "google chrome"
    assert is_comp is False


# ======================================================================
# 2. IntentClassifier Intent & Entity Classification Tests
# ======================================================================

@pytest.mark.asyncio
async def test_classifier_simple_open_chrome():
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    res = await classifier.classify(RecognizedInput(text="open chrome"))
    assert res.category == IntentCategory.OPEN_APPLICATION
    assert res.entities.get("application") == "chrome"
    assert res.entities.get("is_compound") is None
    assert res.confidence >= 0.7


@pytest.mark.asyncio
async def test_classifier_simple_launch_notepad():
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    res = await classifier.classify(RecognizedInput(text="launch notepad"))
    assert res.category == IntentCategory.OPEN_APPLICATION
    assert res.entities.get("application") == "notepad"
    assert res.entities.get("is_compound") is None
    assert res.confidence >= 0.7


@pytest.mark.asyncio
async def test_classifier_simple_reduce_volume():
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    res = await classifier.classify(RecognizedInput(text="reduce volume"))
    assert res.category == IntentCategory.SET_VOLUME
    assert res.entities.get("action") == "decrease"
    assert res.confidence >= 0.7


@pytest.mark.asyncio
async def test_classifier_multi_word_app_remains_deterministic():
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    res = await classifier.classify(RecognizedInput(text="open visual studio code"))
    assert res.category == IntentCategory.OPEN_APPLICATION
    assert res.entities.get("application") == "visual studio code"
    assert res.entities.get("is_compound") is None
    assert res.confidence >= 0.7


@pytest.mark.asyncio
async def test_classifier_critical_compound_not_greedy():
    """CRITICAL: 'open chrome search youtube for spider man' must NOT capture compound sentence as app."""
    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    res = await classifier.classify(RecognizedInput(text="open chrome search youtube for spider man"))
    assert res.category == IntentCategory.OPEN_APPLICATION
    assert res.entities.get("application") == "chrome"
    assert res.entities.get("application") != "chrome search youtube for spider man"
    assert res.entities.get("is_compound") is True
    assert res.confidence < 0.7


# ======================================================================
# 3. Planner Deterministic Fast-Path Safety Tests
# ======================================================================

@pytest.mark.asyncio
async def test_planner_deterministic_open_chrome():
    planner = Planner()
    await planner.initialize()

    intent = IntentResult(
        category=IntentCategory.OPEN_APPLICATION,
        confidence=0.9,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"application": "chrome"},
    )

    with patch.object(planner._llm_manager, "process") as mock_process:
        plan = await planner.plan("open chrome", intent, None)
        mock_process.assert_not_called()
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters["application"] == "chrome"


@pytest.mark.asyncio
async def test_planner_deterministic_launch_notepad():
    planner = Planner()
    await planner.initialize()

    intent = IntentResult(
        category=IntentCategory.OPEN_APPLICATION,
        confidence=0.9,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"application": "notepad"},
    )

    with patch.object(planner._llm_manager, "process") as mock_process:
        plan = await planner.plan("launch notepad", intent, None)
        mock_process.assert_not_called()
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters["application"] == "notepad"


@pytest.mark.asyncio
async def test_planner_deterministic_reduce_volume():
    planner = Planner()
    await planner.initialize()

    intent = IntentResult(
        category=IntentCategory.SET_VOLUME,
        confidence=0.9,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"action": "decrease", "amount": 10},
    )

    with patch.object(planner._llm_manager, "process") as mock_process:
        plan = await planner.plan("reduce volume", intent, None)
        mock_process.assert_not_called()
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "set_volume"
        assert plan.steps[0].parameters["action"] == "decrease"


@pytest.mark.asyncio
async def test_planner_deterministic_multi_word_visual_studio_code():
    """Multi-word application name must remain on deterministic fast path."""
    planner = Planner()
    await planner.initialize()

    intent = IntentResult(
        category=IntentCategory.OPEN_APPLICATION,
        confidence=0.9,
        confidence_level=ConfidenceLevel.HIGH,
        entities={"application": "visual studio code"},
    )

    with patch.object(planner._llm_manager, "process") as mock_process:
        plan = await planner.plan("open visual studio code", intent, None)
        mock_process.assert_not_called()
        assert len(plan.steps) == 1
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters["application"] == "visual studio code"


@pytest.mark.asyncio
async def test_planner_critical_compound_routes_to_llm():
    """
    CRITICAL TEST:
    'open chrome search youtube for spider man' MUST NOT produce:
    open_application(application="chrome search youtube for spider man")
    It MUST route to LLM planning.
    """
    planner = Planner()
    await planner.initialize()

    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    intent = await classifier.classify(RecognizedInput(text="open chrome search youtube for spider man"))

    # Intent entities must NOT have the full compound command as the application
    assert intent.entities.get("application") != "chrome search youtube for spider man"

    # Mock LLM response returning decomposed multi-step plan
    mock_llm_response = MagicMock()
    mock_llm_response.plan = ExecutionPlan(
        steps=[
            PlanStep(tool="open_application", parameters={"application": "chrome"}, depends_on=[]),
            PlanStep(tool="web_search", parameters={"query": "spider man"}, depends_on=[0]),
        ],
        description="Open Chrome and search for spider man",
    )

    with patch.object(planner._llm_manager, "process", new_callable=AsyncMock, return_value=mock_llm_response) as mock_llm:
        plan = await planner.plan("open chrome search youtube for spider man", intent, None)
        # LLM MUST be called (cannot take deterministic fast path)
        mock_llm.assert_awaited_once()
        assert len(plan.steps) == 2
        assert plan.steps[0].tool == "open_application"
        assert plan.steps[0].parameters["application"] == "chrome"
        assert plan.steps[1].tool == "web_search"
        assert plan.steps[1].parameters["query"] == "spider man"


@pytest.mark.asyncio
async def test_planner_compound_with_conjunction_routes_to_llm():
    planner = Planner()
    await planner.initialize()

    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    intent = await classifier.classify(RecognizedInput(text="open chrome and search youtube for spider man"))

    mock_llm_response = MagicMock()
    mock_llm_response.plan = ExecutionPlan(
        steps=[
            PlanStep(tool="open_application", parameters={"application": "chrome"}, depends_on=[]),
            PlanStep(tool="web_search", parameters={"query": "spider man"}, depends_on=[0]),
        ],
        description="Open Chrome then search",
    )

    with patch.object(planner._llm_manager, "process", new_callable=AsyncMock, return_value=mock_llm_response) as mock_llm:
        plan = await planner.plan("open chrome and search youtube for spider man", intent, None)
        mock_llm.assert_awaited_once()
        assert len(plan.steps) == 2


@pytest.mark.asyncio
async def test_planner_compound_terminal_pytest_routes_to_llm():
    planner = Planner()
    await planner.initialize()

    classifier = PlaceholderIntentClassifier()
    await classifier.initialize()
    intent = await classifier.classify(RecognizedInput(text="launch terminal run pytest"))

    mock_llm_response = MagicMock()
    mock_llm_response.plan = ExecutionPlan(
        steps=[
            PlanStep(tool="open_application", parameters={"application": "terminal"}, depends_on=[]),
        ],
        description="Launch terminal",
    )

    with patch.object(planner._llm_manager, "process", new_callable=AsyncMock, return_value=mock_llm_response) as mock_llm:
        plan = await planner.plan("launch terminal run pytest", intent, None)
        mock_llm.assert_awaited_once()


# ======================================================================
# 4. Canonical Skill Schema & Parameter Validation Tests
# ======================================================================

def test_baseskill_canonical_parameters_schema():
    """BaseSkill exposes canonical parameters_schema."""
    class DummySkill(BaseSkill):
        intent = "dummy"
        def can_handle(self, intent_data): return True
        def execute(self, intent_data): return {}

    skill = DummySkill()
    assert hasattr(skill, "parameters_schema")
    assert isinstance(skill.parameters_schema, dict)
    assert skill.parameters_schema.get("type") == "object"


def test_core_skills_expose_canonical_parameters_schema():
    """Core skills have canonical parameters_schema with required parameters."""
    launcher = AppLauncherSkill()
    assert "application" in launcher.parameters_schema["properties"]
    assert "application" in launcher.parameters_schema["required"]

    closer = AppCloserSkill()
    assert "application" in closer.parameters_schema["properties"]
    assert "application" in closer.parameters_schema["required"]

    search = SearchSkill()
    assert "query" in search.parameters_schema["properties"]
    assert "query" in search.parameters_schema["required"]

    chrome = ChromeSkill()
    assert "url" in chrome.parameters_schema["properties"]

    edge = EdgeSkill()
    assert "url" in edge.parameters_schema["properties"]

    volume = VolumeSkill()
    assert "action" in volume.parameters_schema["properties"]
    assert "action" in volume.parameters_schema["required"]


def test_registry_exposes_tool_definitions_with_parameters_schema():
    """SkillRegistry exposes dynamic tool definitions containing parameters_schema."""
    tools = registry.get_tool_definitions()
    assert len(tools) > 0
    for tool_def in tools:
        assert "tool" in tool_def
        assert "description" in tool_def
        assert "parameters_schema" in tool_def
        assert isinstance(tool_def["parameters_schema"], dict)


def test_validator_rejects_missing_required_parameter():
    validator = PlanValidator()
    plan = ExecutionPlan(
        steps=[PlanStep(tool="open_application", parameters={})],
        description="Missing application parameter",
    )
    with pytest.raises(PlanValidationError, match="missing required parameter 'application'"):
        validator.validate(plan)


def test_validator_rejects_invalid_parameter_type():
    validator = PlanValidator()
    plan = ExecutionPlan(
        steps=[PlanStep(tool="open_application", parameters={"application": 12345})],
        description="Invalid application type",
    )
    with pytest.raises(PlanValidationError, match="must be string"):
        validator.validate(plan)


def test_validator_rejects_unknown_tool():
    validator = PlanValidator()
    plan = ExecutionPlan(
        steps=[PlanStep(tool="non_existent_tool_xyz", parameters={})],
        description="Unknown tool",
    )
    with pytest.raises(PlanValidationError, match="non_existent_tool_xyz"):
        validator.validate(plan)


def test_validator_passes_valid_multi_step_plan():
    validator = PlanValidator()
    plan = ExecutionPlan(
        steps=[
            PlanStep(tool="open_application", parameters={"application": "chrome"}, depends_on=[]),
            PlanStep(tool="web_search", parameters={"query": "python"}, depends_on=[0]),
        ],
        description="Valid multi-step plan",
    )
    validated = validator.validate(plan)
    assert len(validated.steps) == 2


def test_validator_rejects_invalid_multi_step_dependency_cycle():
    validator = PlanValidator()
    plan = ExecutionPlan(
        steps=[
            PlanStep(tool="open_application", parameters={"application": "chrome"}, depends_on=[1]),
            PlanStep(tool="web_search", parameters={"query": "python"}, depends_on=[0]),
        ],
        description="Cycle plan",
    )
    with pytest.raises(PlanValidationError):
        validator.validate(plan)
