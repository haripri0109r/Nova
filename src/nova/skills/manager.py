"""
SkillManager – bridges the Intent Router to concrete skills.
"""

import logging
from typing import Any, Dict, Optional

from .registry import registry
from .base import BaseSkill

logger = logging.getLogger("nova.skills.manager")


class SkillManager:
    """
    Receives a validated intent (as dict), finds the appropriate skill,
    executes it, and returns a result dict.
    """

    def __init__(self) -> None:
        self._registry = registry

    def execute_intent(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point called by the router.

        Returns a dict with at least:
        {
            "status": "ok" | "error" | "not_found",
            "result": ...,
            "skill": <skill name>,
            "message": <optional>
        }
        """
        intent_name = intent_data.get("intent")
        if not intent_name:
            logger.error("Intent data missing 'intent' field: %s", intent_data)
            return {"status": "error", "message": "Missing intent field"}

        skill = self._registry.get(intent_name)
        if skill is None:
            logger.warning("No skill registered for intent %r", intent_name)
            return {"status": "not_found", "message": f"No skill for intent {intent_name}"}

        logger.info("Executing skill %s for intent %s", skill.__class__.__name__, intent_name)
        try:
            # Ensure skill can handle (double-check)
            if not skill.can_handle(intent_data):
                logger.warning("Skill %s cannot handle intent data %s", skill, intent_data)
                return {"status": "error", "message": f"Skill {skill} cannot handle this intent"}

            result = skill.execute(intent_data)
            logger.debug("Skill %s returned: %s", skill, result)
            return {
                "status": "ok",
                "result": result,
                "skill": skill.__class__.__name__,
            }
        except Exception:
            logger.exception("Skill %s raised an exception", skill.__class__.__name__)
            return {"status": "error", "message": "Skill execution failed"}

    # Convenience for testing / manual invocation
    def get_skill(self, intent_name: str) -> Optional[BaseSkill]:
        return self._registry.get(intent_name)


# Global singleton
_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager