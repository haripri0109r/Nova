"""
SkillManager – bridges the Intent Router to concrete skills.
"""

import asyncio
import inspect
import logging
from typing import Any, Dict, Optional

from .registry import registry
from .base import BaseSkill

logger = logging.getLogger("nova.skills.manager")


class SkillManager:
    """
    Receives a validated intent (as dict), finds the appropriate skill,
    executes it, and returns a result dict. Supports both async and sync skills.
    """

    def __init__(self) -> None:
        self._registry = registry

    async def execute_intent_async(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Asynchronously execute an intent with the appropriate registered skill.
        Handles both synchronous and asynchronous skills cleanly without unawaited coroutines.
        """
        intent_name = intent_data.get("intent")
        if not intent_name:
            logger.error("Intent data missing 'intent' field: %s", intent_data)
            return {"status": "error", "message": "Missing intent field"}

        skill = self._registry.get(intent_name, intent_data)
        if skill is None:
            logger.warning("No skill registered for intent %r (data: %s)", intent_name, intent_data)
            return {"status": "not_found", "message": f"No skill for intent {intent_name}"}

        logger.info("Executing skill %s for intent %s", skill.__class__.__name__, intent_name)
        try:
            if not skill.can_handle(intent_data):
                logger.warning("Skill %s cannot handle intent data %s", skill, intent_data)
                return {"status": "error", "message": f"Skill {skill} cannot handle this intent"}

            if inspect.iscoroutinefunction(skill.execute):
                result = await skill.execute(intent_data)
            else:
                result = skill.execute(intent_data)
                if inspect.isawaitable(result):
                    result = await result

            logger.debug("Skill %s returned: %s", skill, result)

            if isinstance(result, dict) and result.get("status") == "error":
                return {
                    "status": "error",
                    "message": result.get("message", "Skill returned error"),
                    "skill": skill.__class__.__name__,
                }

            return {
                "status": "ok",
                "result": result,
                "skill": skill.__class__.__name__,
            }
        except Exception:
            logger.exception("Skill %s raised an exception", skill.__class__.__name__)
            return {"status": "error", "message": "Skill execution failed"}

    def execute_intent(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Synchronous entry point for callers without an async context.
        If an async skill is invoked from inside a running event loop, raises RuntimeError.
        """
        intent_name = intent_data.get("intent")
        if not intent_name:
            logger.error("Intent data missing 'intent' field: %s", intent_data)
            return {"status": "error", "message": "Missing intent field"}

        skill = self._registry.get(intent_name, intent_data)
        if skill is None:
            logger.warning("No skill registered for intent %r", intent_name)
            return {"status": "not_found", "message": f"No skill for intent {intent_name}"}

        # Check if the skill execution is asynchronous
        is_async = inspect.iscoroutinefunction(skill.execute)

        if is_async:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Deliberate backward-compatibility: When a synchronous caller (such as legacy or
                # workflow engines) calls execute_intent from within a running event loop, running
                # asyncio.run in a separate worker thread avoids both nested event loops and blocking
                # run_until_complete on the active loop.
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    return pool.submit(asyncio.run, self.execute_intent_async(intent_data)).result()
            return asyncio.run(self.execute_intent_async(intent_data))

        # Synchronous execution for standard sync skill
        logger.info("Executing skill %s for intent %s", skill.__class__.__name__, intent_name)
        try:
            if not skill.can_handle(intent_data):
                logger.warning("Skill %s cannot handle intent data %s", skill, intent_data)
                return {"status": "error", "message": f"Skill {skill} cannot handle this intent"}

            result = skill.execute(intent_data)
            if inspect.isawaitable(result):
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None
                if loop and loop.is_running():
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                        result = pool.submit(asyncio.run, result).result()
                else:
                    result = asyncio.run(result)

            logger.debug("Skill %s returned: %s", skill, result)

            if isinstance(result, dict) and result.get("status") == "error":
                return {
                    "status": "error",
                    "message": result.get("message", "Skill returned error"),
                    "skill": skill.__class__.__name__,
                }

            return {
                "status": "ok",
                "result": result,
                "skill": skill.__class__.__name__,
            }
        except Exception:
            logger.exception("Skill %s raised an exception", skill.__class__.__name__)
            return {"status": "error", "message": "Skill execution failed"}

    def get_skill(self, intent_name: str, intent_data: Optional[Dict[str, Any]] = None) -> Optional[BaseSkill]:
        return self._registry.get(intent_name, intent_data)

    async def initialize(self) -> bool:
        """Initialize the skill manager and all registered skills."""
        await self._registry.initialize_all()
        return True

    async def cleanup(self) -> None:
        """Cleanup the skill manager and all registered skills."""
        await self._registry.cleanup_all()


# Global singleton
_skill_manager: Optional[SkillManager] = None


def get_skill_manager() -> SkillManager:
    global _skill_manager
    if _skill_manager is None:
        _skill_manager = SkillManager()
    return _skill_manager