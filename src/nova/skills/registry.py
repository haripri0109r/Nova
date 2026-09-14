"""
Skill registry – automatically discovers and stores all concrete BaseSkill subclasses.
"""

import logging
from typing import Any, Dict, List, Optional

from .base import BaseSkill

logger = logging.getLogger("nova.skills.registry")


class _SkillsDict(dict):
    """Custom dictionary to keep _skills and _skills_by_intent in sync when tests manipulate _skills directly."""
    def __init__(self, registry_ref, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._registry_ref = registry_ref

    def clear(self):
        super().clear()
        self._registry_ref._skills_by_intent.clear()

    def update(self, *args, **kwargs):
        super().update(*args, **kwargs)
        for skill in self.values():
            if isinstance(skill, BaseSkill) and skill.intent:
                candidates = self._registry_ref._skills_by_intent.setdefault(skill.intent, [])
                if skill not in candidates:
                    candidates.append(skill)

    def pop(self, key, default=None):
        val = super().pop(key, default)
        self._registry_ref._skills_by_intent.pop(key, None)
        return val

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if isinstance(value, BaseSkill) and value.intent:
            candidates = self._registry_ref._skills_by_intent.setdefault(value.intent, [])
            if value not in candidates:
                candidates.insert(0, value)

    def __delitem__(self, key):
        super().__delitem__(key)
        self._registry_ref._skills_by_intent.pop(key, None)


INTENT_ALIASES: Dict[str, str] = {
    "bluetooth_control": "bluetooth",
    "wifi_control": "wifi",
    "volume_control": "set_volume",
    "brightness_control": "set_brightness",
    "settings": "open_settings",
    "set_personalization": "personalization",
}


class SkillRegistry:
    """
    Holds a mapping intent -> skill instances, supporting multiple skills
    for the same intent with deterministic selection via can_handle().
    """

    def __init__(self) -> None:
        self._skills_by_intent: Dict[str, List[BaseSkill]] = {}
        self._skills: Dict[str, BaseSkill] = _SkillsDict(self)

    def register(self, skill: BaseSkill) -> None:
        """Register a skill instance. Explicitly tracks multiple skills for an intent."""
        if not skill.intent:
            logger.warning("Attempted to register skill %s without an intent", skill)
            return

        candidates = self._skills_by_intent.setdefault(skill.intent, [])
        if skill not in candidates:
            # Prepend newest registered skill so test mocks / explicit additions have precedence
            candidates.insert(0, skill)
            logger.debug(
                "Registered skill %s for intent %r (total candidates: %d)",
                skill.__class__.__name__,
                skill.intent,
                len(candidates),
            )

        self._skills[skill.intent] = candidates[0]

    def get(self, intent: str, intent_data: Optional[Dict[str, Any]] = None) -> Optional[BaseSkill]:
        """
        Retrieve a skill by its intent.
        If multiple skills match the intent and intent_data is provided,
        determines the matching skill using can_handle(intent_data).
        If no candidate matches the specific intent_data, returns None.
        If intent_data is None, returns the primary candidate.
        """
        canonical = INTENT_ALIASES.get(intent, intent)
        candidates = self._skills_by_intent.get(canonical, [])
        if not candidates:
            return self._skills.get(canonical)

        if intent_data is not None and len(candidates) > 1:
            for candidate in candidates:
                try:
                    if candidate.can_handle(intent_data):
                        return candidate
                except Exception as exc:
                    logger.warning("Error checking can_handle on %s: %s", candidate, exc)
            return None

        return candidates[0]

    def get_all_for_intent(self, intent: str) -> List[BaseSkill]:
        """Return all skills registered for a given intent."""
        return list(self._skills_by_intent.get(intent, []))

    def all(self) -> List[BaseSkill]:
        """Return all unique registered skills."""
        unique: List[BaseSkill] = []
        for candidate_list in self._skills_by_intent.values():
            for skill in candidate_list:
                if skill not in unique:
                    unique.append(skill)
        return unique

    def get_tool_definitions(self) -> List[Dict[str, Any]]:
        """Return canonical tool definitions from registered skills for LLM planning."""
        tools: List[Dict[str, Any]] = []
        seen_intents = set()
        for skill in self.all():
            if skill.intent and skill.intent not in seen_intents:
                seen_intents.add(skill.intent)
                schema = getattr(skill, "parameters_schema", None)
                if schema is None:
                    schema = getattr(skill, "parameter_schema", {})
                tools.append({
                    "tool": skill.intent,
                    "description": skill.description,
                    "parameters_schema": schema if isinstance(schema, dict) else {},
                    "parameters": schema if isinstance(schema, dict) else {},
                })
        return tools

    async def initialize_all(self) -> None:
        """Initialize all registered skills."""
        for skill in self.all():
            try:
                if hasattr(skill, "initialize"):
                    await skill.initialize()
                logger.info("Initialized skill: %s (%s)", skill.intent, skill.__class__.__name__)
            except Exception as e:
                logger.error("Failed to initialize skill %s: %s", skill, e)
                raise

    async def cleanup_all(self) -> None:
        """Cleanup all registered skills."""
        for skill in self.all():
            try:
                if hasattr(skill, "cleanup"):
                    await skill.cleanup()
                logger.info("Cleaned up skill: %s (%s)", skill.intent, skill.__class__.__name__)
            except Exception as e:
                logger.error("Error cleaning up skill %s: %s", skill, e)
                raise


# Global singleton used by the SkillManager
registry = SkillRegistry()