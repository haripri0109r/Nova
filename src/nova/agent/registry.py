"""Skill registry implementation."""
from __future__ import annotations
from typing import Dict, List, Optional
from .interfaces import Skill, SkillRegistry
from .models import SkillDefinition
from .exceptions import SkillNotFoundError, RegistryError

import logging
logger = logging.getLogger("nova.agent.registry")


class SkillRegistryImpl(SkillRegistry):
    """Concrete implementation of SkillRegistry."""

    def __init__(self):
        self._skills: Dict[str, object] = {}
        self._definitions: Dict[str, SkillDefinition] = {}

    def register(self, skill: object) -> None:
        """Register a skill instance."""
        from .interfaces import Skill
        if not isinstance(skill, Skill):
            raise TypeError(f"Expected Skill instance, got {type(skill)}")
        if skill.name in self._skills:
            logger.warning(f"Skill '{skill.name}' already registered, overwriting.")
        self._skills[skill.name] = skill
        self._definitions[skill.name] = skill.definition
        logger.info(f"Registered skill: {skill.name}")

    def unregister(self, name: str) -> None:
        """Unregister a skill by name."""
        if name not in self._skills:
            raise SkillNotFoundError(name)
        del self._skills[name]
        del self._definitions[name]
        logger.info(f"Unregistered skill: {name}")

    def get(self, name: str) -> object:
        """Get a skill by name."""
        if name not in self._skills:
            raise SkillNotFoundError(name)
        return self._skills[name]

    def resolve(self, name: str) -> object:
        """
        Retrieve a skill by name.

        Raises:
            SkillNotFoundError: if no skill with the given name is registered.
        """
        if name not in self._skills:
            raise SkillNotFoundError(name)
        return self._skills[name]

    def exists(self, name: str) -> bool:
        """Return True if a skill with the given name is registered."""
        return name in self._skills

    def list_skills(self) -> List[SkillDefinition]:
        """List all registered skills."""
        return list(self._definitions.values())

    async def initialize_all(self) -> None:
        """Initialize all registered skills."""
        for name, skill in self._skills.items():
            try:
                await skill.initialize()
                logger.info(f"Initialized skill: {name}")
            except Exception as e:
                logger.error(f"Failed to initialize skill {name}: {e}")
                raise

    async def cleanup_all(self) -> None:
        """Cleanup all registered skills."""
        for name, skill in self._skills.items():
            try:
                await skill.cleanup()
                logger.info(f"Cleaned up skill: {name}")
            except Exception as e:
                logger.error(f"Error cleaning up skill {name}: {e}")
                raise


# Use the skills registry as the single source of truth
def get_skill_registry():
    """Get global skill registry instance from skills package."""
    from nova.skills.registry import registry
    return registry


# For backward compatibility
SkillRegistry = __import__('nova.skills.registry', fromlist=['SkillRegistry']).SkillRegistry