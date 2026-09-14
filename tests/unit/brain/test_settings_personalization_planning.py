"""
Brain and Planning Unit Tests for Phase 5.8-B.

Verifies:
- Intent classification for settings navigation and personalization
- Correct entity extraction (page, feature, mode, alignment, path)
- Deterministic fast path execution without LLM invocation for safe simple commands
- PlanStep compliance with canonical SkillRegistry parameter schemas
- PlanValidator passes valid plans and rejects schema violations
- Multi-step compound planning for combined settings and personalization commands
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from nova.brain.intent_classifier import PlaceholderIntentClassifier
from nova.brain.planner import Planner
from nova.brain.validator import PlanValidator
from nova.brain.types import IntentCategory, ConfidenceLevel
from nova.brain.models import RecognizedInput, IntentResult, ExecutionPlan, PlanStep
from nova.brain.exceptions import PlanValidationError
from nova.skills.registry import registry
from nova.skills.system.settings import SettingsSkill
from nova.skills.system.personalization import PersonalizationSkill


@pytest.fixture(autouse=True)
def setup_skills():
    """Ensure SettingsSkill and PersonalizationSkill are registered."""
    settings_skill = SettingsSkill()
    personalization_skill = PersonalizationSkill()
    registry.register(settings_skill)
    registry.register(personalization_skill)
    yield


class TestIntentClassification:
    def setup_method(self):
        self.classifier = PlaceholderIntentClassifier()

    @pytest.mark.asyncio
    async def test_open_display_settings(self):
        res = await self.classifier.classify(RecognizedInput(text="open display settings"))
        assert res.category == IntentCategory.OPEN_SETTINGS
        assert res.entities.get("page") == "display"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_open_wifi_settings(self):
        res = await self.classifier.classify(RecognizedInput(text="open wifi settings"))
        assert res.category == IntentCategory.OPEN_SETTINGS
        assert res.entities.get("page") == "wifi"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_open_default_apps(self):
        res = await self.classifier.classify(RecognizedInput(text="open default apps"))
        assert res.category == IntentCategory.OPEN_SETTINGS
        assert res.entities.get("page") == "default_apps"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_change_default_browser_routes_to_settings(self):
        res = await self.classifier.classify(RecognizedInput(text="change my default browser"))
        assert res.category == IntentCategory.OPEN_SETTINGS
        assert res.entities.get("page") == "default_apps"

    @pytest.mark.asyncio
    async def test_turn_on_dark_mode(self):
        res = await self.classifier.classify(RecognizedInput(text="turn on dark mode"))
        assert res.category == IntentCategory.PERSONALIZATION
        assert res.entities.get("feature") == "theme"
        assert res.entities.get("mode") == "dark"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_switch_to_light_mode(self):
        res = await self.classifier.classify(RecognizedInput(text="switch to light mode"))
        assert res.category == IntentCategory.PERSONALIZATION
        assert res.entities.get("feature") == "theme"
        assert res.entities.get("mode") == "light"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_center_the_taskbar(self):
        res = await self.classifier.classify(RecognizedInput(text="center the taskbar"))
        assert res.category == IntentCategory.PERSONALIZATION
        assert res.entities.get("feature") == "taskbar"
        assert res.entities.get("alignment") == "center"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_move_taskbar_to_the_left(self):
        res = await self.classifier.classify(RecognizedInput(text="move the taskbar to the left"))
        assert res.category == IntentCategory.PERSONALIZATION
        assert res.entities.get("feature") == "taskbar"
        assert res.entities.get("alignment") == "left"
        assert res.confidence >= 0.8

    @pytest.mark.asyncio
    async def test_set_wallpaper(self):
        res = await self.classifier.classify(RecognizedInput(text=r"set wallpaper to C:\test\wallpaper.jpg"))
        assert res.category == IntentCategory.PERSONALIZATION
        assert res.entities.get("feature") == "wallpaper"
        assert res.entities.get("path") == r"C:\test\wallpaper.jpg"
        assert res.confidence >= 0.8


class TestDeterministicPlanningFastPath:
    @pytest.mark.asyncio
    async def test_open_settings_fast_path(self):
        mock_llm = MagicMock()
        mock_llm.process = AsyncMock()
        planner = Planner(llm_manager=mock_llm, skill_registry=registry)
        validator = PlanValidator(registry)

        intent = IntentResult(
            category=IntentCategory.OPEN_SETTINGS,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"page": "display"},
        )

        plan = await planner.plan("open display settings", intent)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.tool == "open_settings"
        assert step.parameters == {"page": "display"}
        assert step.depends_on == []
        mock_llm.process.assert_not_called()

        # Verify plan passes validator
        validated = validator.validate(plan)
        assert validated is plan

    @pytest.mark.asyncio
    async def test_theme_fast_path(self):
        mock_llm = MagicMock()
        mock_llm.process = AsyncMock()
        planner = Planner(llm_manager=mock_llm, skill_registry=registry)
        validator = PlanValidator(registry)

        intent = IntentResult(
            category=IntentCategory.PERSONALIZATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"feature": "theme", "mode": "dark"},
        )

        plan = await planner.plan("turn on dark mode", intent)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.tool == "personalization"
        assert step.parameters == {"feature": "theme", "mode": "dark"}
        assert step.depends_on == []
        mock_llm.process.assert_not_called()

        validated = validator.validate(plan)
        assert validated is plan

    @pytest.mark.asyncio
    async def test_taskbar_fast_path(self):
        mock_llm = MagicMock()
        mock_llm.process = AsyncMock()
        planner = Planner(llm_manager=mock_llm, skill_registry=registry)
        validator = PlanValidator(registry)

        intent = IntentResult(
            category=IntentCategory.PERSONALIZATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"feature": "taskbar", "alignment": "center"},
        )

        plan = await planner.plan("center the taskbar", intent)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.tool == "personalization"
        assert step.parameters == {"feature": "taskbar", "alignment": "center"}
        assert step.depends_on == []
        mock_llm.process.assert_not_called()

        validated = validator.validate(plan)
        assert validated is plan

    @pytest.mark.asyncio
    async def test_wallpaper_fast_path(self):
        mock_llm = MagicMock()
        mock_llm.process = AsyncMock()
        planner = Planner(llm_manager=mock_llm, skill_registry=registry)
        validator = PlanValidator(registry)

        intent = IntentResult(
            category=IntentCategory.PERSONALIZATION,
            confidence=0.9,
            confidence_level=ConfidenceLevel.HIGH,
            entities={"feature": "wallpaper", "path": r"C:\test\wallpaper.jpg"},
        )

        plan = await planner.plan(r"set wallpaper to C:\test\wallpaper.jpg", intent)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 1
        step = plan.steps[0]
        assert step.tool == "personalization"
        assert step.parameters == {"feature": "wallpaper", "path": r"C:\test\wallpaper.jpg"}
        assert step.depends_on == []
        mock_llm.process.assert_not_called()

        validated = validator.validate(plan)
        assert validated is plan


class TestPlanValidationRejections:
    def test_invalid_settings_parameter(self):
        validator = PlanValidator(registry)
        # Missing page
        plan = ExecutionPlan(steps=[PlanStep(id="s1", tool="open_settings", parameters={})])
        with pytest.raises(PlanValidationError, match="page"):
            validator.validate(plan)

        # Unexpected parameter
        plan2 = ExecutionPlan(steps=[PlanStep(id="s2", tool="open_settings", parameters={"page": "display", "invalid": 1})])
        with pytest.raises(PlanValidationError):
            validator.validate(plan2)

    def test_invalid_personalization_parameter(self):
        validator = PlanValidator(registry)
        # Missing feature
        plan = ExecutionPlan(steps=[PlanStep(id="s1", tool="personalization", parameters={})])
        with pytest.raises(PlanValidationError, match="feature"):
            validator.validate(plan)

        # Invalid feature enum
        plan2 = ExecutionPlan(steps=[PlanStep(id="s2", tool="personalization", parameters={"feature": "audio"})])
        with pytest.raises(PlanValidationError):
            validator.validate(plan2)

        # Invalid theme mode
        plan3 = ExecutionPlan(steps=[PlanStep(id="s3", tool="personalization", parameters={"feature": "theme", "mode": "neon"})])
        with pytest.raises(PlanValidationError):
            validator.validate(plan3)

        # Invalid taskbar alignment
        plan4 = ExecutionPlan(steps=[PlanStep(id="s4", tool="personalization", parameters={"feature": "taskbar", "alignment": "top"})])
        with pytest.raises(PlanValidationError):
            validator.validate(plan4)


class TestCompoundCommandPlanning:
    @pytest.mark.asyncio
    async def test_compound_open_settings_and_dark_mode(self):
        """
        'open display settings and then turn on dark mode'
        Must NOT be collapsed into open_settings(page="display and then turn on dark mode").
        Must produce multi-step plan with dependency.
        """
        classifier = PlaceholderIntentClassifier()
        classified = await classifier.classify(RecognizedInput(text="open display settings and then turn on dark mode"))
        assert classified.entities.get("is_compound") is True

        mock_llm = MagicMock()
        mock_llm.process = AsyncMock(return_value="""{
            "steps": [
                {"tool": "open_settings", "parameters": {"page": "display"}, "depends_on": []},
                {"tool": "personalization", "parameters": {"feature": "theme", "mode": "dark"}, "depends_on": [0]}
            ],
            "description": "Open display settings and turn on dark mode"
        }""")

        planner = Planner(llm_manager=mock_llm, skill_registry=registry)
        validator = PlanValidator(registry)

        plan = await planner.plan("open display settings and then turn on dark mode", classified)

        assert mock_llm.process.called
        assert len(plan.steps) == 2

        # Step 0
        assert plan.steps[0].tool == "open_settings"
        assert plan.steps[0].parameters == {"page": "display"}
        assert plan.steps[0].depends_on == []

        # Step 1
        assert plan.steps[1].tool == "personalization"
        assert plan.steps[1].parameters == {"feature": "theme", "mode": "dark"}
        assert plan.steps[1].depends_on == [0]

        # Verify structural validity
        validated = validator.validate(plan)
        assert validated is plan
