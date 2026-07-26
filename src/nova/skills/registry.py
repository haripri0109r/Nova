"""
Skill registry – automatically discovers and stores all concrete BaseSkill subclasses.
"""

import logging
from typing import Dict, List

from .base import BaseSkill

logger = logging.getLogger("nova.skills.registry")


class SkillRegistry:
    """
    Holds a mapping intent -> skill instance.
    """

    def __init__(self) -> None:
        self._skills: Dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill) -> None:
        """Register a skill instance."""
        if skill.intent in self._skills:
            logger.warning(
                "Skill for intent %r already registered (%s), overwriting.",
                skill.intent,
                self._skills[skill.intent],
            )
        self._skills[skill.intent] = skill
        logger.debug("Registered skill %s for intent %r", skill, skill.intent)

    def get(self, intent: str) -> BaseSkill | None:
        """Retrieve a skill by its primary intent."""
        return self._skills.get(intent)

    def all(self) -> List[BaseSkill]:
        """Return all registered skills."""
        return list(self._skills.values())


# Global singleton used by the SkillManager
registry = SkillRegistry()