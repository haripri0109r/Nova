"""
Unit tests for Phase 5.5B — Production Skill Parameter Schema Completion.

Verifies:
A. Every concrete non-frozen production skill has parameters_schema.
B. Every schema is JSON-Schema-compatible.
C. Required fields are enforced.
D. Parameter types are enforced.
E. Enum values are enforced where applicable.
F. Unexpected parameters are rejected where schema disallows them (additionalProperties: False).
G. Valid parameters pass validation.
H. Registry exports the canonical schemas without duplicates.
I. PromptBuilder receives the canonical schemas from SkillRegistry.
J. Shutdown and restart remain confirmation-gated.
"""

import pytest
from typing import Any, Dict, List

from nova.skills.registry import registry
from nova.skills.base import BaseSkill
from nova.skills.applications.launcher import AppLauncherSkill
from nova.skills.applications.closer import AppCloserSkill
from nova.skills.browser.chrome import ChromeSkill
from nova.skills.browser.edge import EdgeSkill
from nova.skills.browser.search import SearchSkill
from nova.skills.files.explorer import ExplorerSkill
from nova.skills.files.search import FileSearchSkill
from nova.skills.media.spotify import SpotifySkill
from nova.skills.media.youtube import YouTubeSkill
from nova.skills.system.bluetooth import BluetoothSkill
from nova.skills.system.brightness import BrightnessSkill
from nova.skills.system.lock import LockSkill
from nova.skills.system.restart import RestartSkill
from nova.skills.system.settings import SettingsSkill
from nova.skills.system.personalization import PersonalizationSkill
from nova.skills.system.shutdown import ShutdownSkill
from nova.skills.system.sleep import SleepSkill
from nova.skills.system.volume import VolumeSkill
from nova.skills.system.wifi import WifiSkill
from nova.skills.system.network import NetworkSkill
from nova.skills.system.window import WindowSkill

from nova.brain.validator import PlanValidator
from nova.brain.models import ExecutionPlan, PlanStep
from nova.brain.exceptions import PlanValidationError
from nova.llm.prompt_builder import get_active_tool_definitions
from nova.agent.step_risk_policy import classify_step_risk, RiskLevel


CONCRETE_PRODUCTION_SKILLS = [
    AppLauncherSkill,
    AppCloserSkill,
    ChromeSkill,
    EdgeSkill,
    SearchSkill,
    ExplorerSkill,
    FileSearchSkill,
    SpotifySkill,
    YouTubeSkill,
    BluetoothSkill,
    BrightnessSkill,
    LockSkill,
    RestartSkill,
    SettingsSkill,
    PersonalizationSkill,
    ShutdownSkill,
    SleepSkill,
    VolumeSkill,
    WifiSkill,
    NetworkSkill,
    WindowSkill,
]


@pytest.fixture(autouse=True)
def setup_skill_registry():
    """Ensure all concrete production skills are registered in the registry."""
    for skill_cls in CONCRETE_PRODUCTION_SKILLS:
        registry.register(skill_cls())
    yield


def test_every_concrete_production_skill_has_parameters_schema():
    """A: Every concrete non-frozen production skill must expose a canonical parameters_schema."""
    for skill_cls in CONCRETE_PRODUCTION_SKILLS:
        skill = skill_cls()
        schema = getattr(skill, "parameters_schema", None)
        assert schema is not None, f"{skill_cls.__name__} missing parameters_schema"
        assert isinstance(schema, dict), f"{skill_cls.__name__}.parameters_schema must be a dict"
        assert schema.get("type") == "object", f"{skill_cls.__name__}.parameters_schema type must be 'object'"
        assert "properties" in schema, f"{skill_cls.__name__}.parameters_schema missing 'properties'"
        assert isinstance(schema["properties"], dict), f"{skill_cls.__name__} properties must be dict"
        assert "required" in schema, f"{skill_cls.__name__}.parameters_schema missing 'required'"
        assert isinstance(schema["required"], list), f"{skill_cls.__name__} required must be list"


def test_schemas_are_json_schema_compatible():
    """B: Schemas must be valid JSON Schema objects with correct property type definitions."""
    for skill_cls in CONCRETE_PRODUCTION_SKILLS:
        skill = skill_cls()
        schema = skill.parameters_schema
        for prop_name, prop_spec in schema["properties"].items():
            assert isinstance(prop_spec, dict), f"Property {prop_name} in {skill_cls.__name__} must be a dict"
            if "type" in prop_spec:
                prop_type = prop_spec["type"]
                if isinstance(prop_type, list):
                    for t in prop_type:
                        assert t in ("string", "integer", "number", "boolean", "object", "array")
                else:
                    assert prop_type in ("string", "integer", "number", "boolean", "object", "array")
            if "enum" in prop_spec:
                assert isinstance(prop_spec["enum"], (list, tuple))
                assert len(prop_spec["enum"]) > 0


def test_zero_parameter_skills_have_empty_object_schema():
    """System actions without parameters must expose empty object schema with additionalProperties=False."""
    zero_param_skills = [LockSkill, RestartSkill, ShutdownSkill, SleepSkill]
    for skill_cls in zero_param_skills:
        skill = skill_cls()
        schema = skill.parameters_schema
        assert schema["type"] == "object"
        assert schema["properties"] == {}


def test_required_fields_enforcement():
    """C: Missing required parameter must fail PlanValidator with PlanValidationError."""
    validator = PlanValidator(registry)

    test_cases = [
        ("open_folder", {}, "path"),
        ("find_file", {}, "pattern"),
        ("media_control", {}, "action"),
        ("play_media", {}, "query"),
        ("bluetooth", {}, "action"),
        ("wifi", {}, "action"),
        ("network", {}, "action"),
        ("set_brightness", {}, "action"),
        ("set_volume", {}, "action"),
        ("open_application", {}, "application"),
        ("close_application", {}, "application"),
        ("web_search", {}, "query"),
        ("open_settings", {}, "page"),
        ("personalization", {}, "feature"),
    ]

    for tool, params, missing_field in test_cases:
        plan = ExecutionPlan(steps=[PlanStep(id="s1", tool=tool, parameters=params)])
        with pytest.raises(PlanValidationError) as exc_info:
            validator.validate(plan)
        assert missing_field in str(exc_info.value), f"Expected missing field '{missing_field}' in error for {tool}"


def test_parameter_types_enforcement():
    """D: Wrong parameter types must fail PlanValidator."""
    validator = PlanValidator(registry)

    invalid_type_cases = [
        ("open_folder", {"path": 12345}, "string"),
        ("find_file", {"pattern": True}, "string"),
        ("web_search", {"query": ["not", "a", "string"]}, "string"),
        ("set_volume", {"action": "set", "level": "not_an_int"}, "integer"),
        ("set_brightness", {"action": "set", "level": "one_hundred"}, "integer"),
        ("open_settings", {"page": 123}, "string"),
        ("personalization", {"feature": 123}, "string"),
    ]

    for tool, params, expected_type in invalid_type_cases:
        plan = ExecutionPlan(steps=[PlanStep(id="s1", tool=tool, parameters=params)])
        with pytest.raises(PlanValidationError) as exc_info:
            validator.validate(plan)
        assert expected_type in str(exc_info.value), f"Expected type error mentioning '{expected_type}' for {tool}"


def test_enum_values_enforcement():
    """E: Disallowed enum value must fail PlanValidator with PlanValidationError."""
    validator = PlanValidator(registry)

    enum_cases = [
        ("bluetooth", {"action": "toggle"}),
        ("wifi", {"action": "restart"}),
        ("set_brightness", {"action": "maximum"}),
        ("personalization", {"feature": "invalid_feature"}),
        ("window", {"action": "teleport"}),
        ("window", {"action": "snap", "position": "diagonal"}),
    ]

    for tool, params in enum_cases:
        plan = ExecutionPlan(steps=[PlanStep(id="s1", tool=tool, parameters=params)])
        with pytest.raises(PlanValidationError) as exc_info:
            validator.validate(plan)
        assert "invalid enum value" in str(exc_info.value).lower() or "enum" in str(exc_info.value).lower() or "schema violation" in str(exc_info.value).lower()


def test_unexpected_parameters_rejected_when_disallowed():
    """F: Unexpected parameters must be rejected when additionalProperties is False."""
    validator = PlanValidator(registry)

    disallowed_cases = [
        ("shutdown", {"force": True}),
        ("restart", {"delay": 10}),
        ("lock", {"message": "goodbye"}),
        ("sleep", {"mode": "hibernate"}),
        ("open_settings", {"page": "display", "category": "network"}),
        ("personalization", {"feature": "theme", "mode": "dark", "extra": "unsupported"}),
        ("bluetooth", {"action": "enable", "device": "headphones"}),
        ("wifi", {"action": "disable", "adapter": "wlan0"}),
        ("window", {"action": "minimize", "force": True}),
        ("open_folder", {"path": "C:\\", "extra": "unsupported"}),
        ("find_file", {"pattern": "*.txt", "recursive": True}),
    ]

    for tool, params in disallowed_cases:
        plan = ExecutionPlan(steps=[PlanStep(id="s1", tool=tool, parameters=params)])
        with pytest.raises(PlanValidationError) as exc_info:
            validator.validate(plan)
        assert "unexpected parameter" in str(exc_info.value).lower() or "additional properties" in str(exc_info.value).lower()


def test_valid_parameters_pass_validation():
    """G: Valid parameters for all skills pass validation without error."""
    validator = PlanValidator(registry)

    valid_plans = [
        ExecutionPlan(steps=[PlanStep(id="s1", tool="open_folder", parameters={"path": "C:\\Users"})]),
        ExecutionPlan(steps=[PlanStep(id="s2", tool="find_file", parameters={"pattern": "document.pdf"})]),
        ExecutionPlan(steps=[PlanStep(id="s3", tool="media_control", parameters={"action": "play"})]),
        ExecutionPlan(steps=[PlanStep(id="s4", tool="media_control", parameters={"action": "pause", "app": "spotify"})]),
        ExecutionPlan(steps=[PlanStep(id="s5", tool="play_media", parameters={"query": "classical music"})]),
        ExecutionPlan(steps=[PlanStep(id="s6", tool="bluetooth", parameters={"action": "enable"})]),
        ExecutionPlan(steps=[PlanStep(id="s7", tool="bluetooth", parameters={"action": "disable"})]),
        ExecutionPlan(steps=[PlanStep(id="s8", tool="wifi", parameters={"action": "enable"})]),
        ExecutionPlan(steps=[PlanStep(id="s9", tool="wifi", parameters={"action": "disable"})]),
        ExecutionPlan(steps=[PlanStep(id="s10", tool="set_brightness", parameters={"action": "set", "level": 50})]),
        ExecutionPlan(steps=[PlanStep(id="s11", tool="set_brightness", parameters={"action": "increase", "amount": 10})]),
        ExecutionPlan(steps=[PlanStep(id="s12", tool="set_brightness", parameters={"action": "decrease", "amount": "medium"})]),
        ExecutionPlan(steps=[PlanStep(id="s13", tool="set_volume", parameters={"action": "set", "level": 70})]),
        ExecutionPlan(steps=[PlanStep(id="s14", tool="set_volume", parameters={"action": "increase", "amount": 10})]),
        ExecutionPlan(steps=[PlanStep(id="s15", tool="set_volume", parameters={"action": "decrease", "amount": "small"})]),
        ExecutionPlan(steps=[PlanStep(id="s16", tool="shutdown", parameters={})]),
        ExecutionPlan(steps=[PlanStep(id="s17", tool="restart", parameters={})]),
        ExecutionPlan(steps=[PlanStep(id="s18", tool="lock", parameters={})]),
        ExecutionPlan(steps=[PlanStep(id="s19", tool="sleep", parameters={})]),
        ExecutionPlan(steps=[PlanStep(id="s20", tool="open_settings", parameters={"page": "display"})]),
        ExecutionPlan(steps=[PlanStep(id="s20b", tool="personalization", parameters={"feature": "theme", "mode": "dark"})]),
        ExecutionPlan(steps=[PlanStep(id="s20c", tool="personalization", parameters={"feature": "taskbar", "alignment": "center"})]),
        ExecutionPlan(steps=[PlanStep(id="s20d", tool="personalization", parameters={"feature": "wallpaper", "path": "C:\\wallpaper.jpg"})]),
        ExecutionPlan(steps=[PlanStep(id="s21", tool="open_application", parameters={"application": "notepad"})]),
        ExecutionPlan(steps=[PlanStep(id="s22", tool="close_application", parameters={"application": "calc"})]),
        ExecutionPlan(steps=[PlanStep(id="s23", tool="web_search", parameters={"query": "python"})]),
        ExecutionPlan(steps=[PlanStep(id="s24", tool="open_browser", parameters={"browser": "chrome", "url": "https://example.com"})]),
        ExecutionPlan(steps=[PlanStep(id="s25", tool="network", parameters={"action": "status"})]),
        ExecutionPlan(steps=[PlanStep(id="s26", tool="window", parameters={"action": "minimize", "target": "chrome"})]),
        ExecutionPlan(steps=[PlanStep(id="s27", tool="window", parameters={"action": "snap", "position": "left"})]),
        ExecutionPlan(steps=[PlanStep(id="s28", tool="window", parameters={"action": "show_desktop"})]),
    ]

    for plan in valid_plans:
        validated = validator.validate(plan)
        assert validated is plan


def test_registry_exports_all_canonical_schemas():
    """H: SkillRegistry.get_tool_definitions() returns complete, non-duplicate schemas."""
    tools = registry.get_tool_definitions()
    assert len(tools) > 0

    tool_names = [t["tool"] for t in tools]
    # No duplicate tool definitions
    assert len(tool_names) == len(set(tool_names)), f"Duplicate tools in registry definitions: {tool_names}"

    expected_tools = {
        "open_application", "close_application", "open_browser", "web_search",
        "open_folder", "find_file", "media_control", "play_media",
        "bluetooth", "set_brightness", "lock", "restart",
        "open_settings", "personalization", "shutdown", "sleep", "set_volume", "wifi", "window",
    }

    exported_tools = set(tool_names)
    assert expected_tools.issubset(exported_tools), f"Missing tools from registry: {expected_tools - exported_tools}"

    for t in tools:
        assert "parameters_schema" in t
        assert isinstance(t["parameters_schema"], dict)
        assert t["parameters_schema"].get("type") == "object"


def test_prompt_builder_receives_canonical_registry_schemas():
    """I: PromptBuilder retrieves canonical tool definitions directly from SkillRegistry."""
    prompt_tools = get_active_tool_definitions()
    registry_tools = registry.get_tool_definitions()

    assert len(prompt_tools) == len(registry_tools)
    assert [t["tool"] for t in prompt_tools] == [t["tool"] for t in registry_tools]


def test_shutdown_and_restart_remain_confirmation_gated():
    """L: StepRiskPolicy classifies shutdown/restart as HIGH risk requiring confirmation."""
    assert classify_step_risk("shutdown") == RiskLevel.HIGH
    assert classify_step_risk("shutdown", {}) == RiskLevel.HIGH

    assert classify_step_risk("restart") == RiskLevel.HIGH
    assert classify_step_risk("restart", {}) == RiskLevel.HIGH

    # Normal low-risk tools remain low-risk
    assert classify_step_risk("open_folder", {"path": "C:\\"}) == RiskLevel.LOW
    assert classify_step_risk("set_brightness", {"action": "set", "level": 50}) == RiskLevel.LOW
