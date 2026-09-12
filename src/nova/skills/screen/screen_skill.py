"""
Screen reading skill – returns a natural-language summary of what is currently on screen.
"""
import asyncio
import logging
from typing import Any, Dict

from nova.skills.base import BaseSkill
from nova.skills.registry import registry
from nova.screen.reader import ScreenReader
from nova.llm.manager import get_llm_manager

logger = logging.getLogger("nova.skills.screen.screen_skill")

# Timeout for the blocking UI Automation call (seconds)
SCREEN_READ_TIMEOUT = 5.0


class ScreenSkill(BaseSkill):
    """Skill that reads the active screen and asks the LLM to summarize it."""

    intent = "screen.read"
    description = "Describe what is currently visible on the screen."

    def __init__(self) -> None:
        super().__init__()
        self._screen_reader = None
        self._llm_manager = get_llm_manager()

    def _get_screen_reader(self) -> ScreenReader:
        """Lazily initialize the ScreenReader."""
        if self._screen_reader is None:
            self._screen_reader = ScreenReader()
        return self._screen_reader

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == "screen.read"

    async def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """Read the screen, ask the LLM for a concise spoken summary, and return it."""
        logger.info("ScreenSkill: reading active screen")
        
        try:
            # Run the blocking UI Automation call in a thread with a timeout
            context = await asyncio.wait_for(
                asyncio.to_thread(self._get_screen_reader().read_active_screen),
                timeout=SCREEN_READ_TIMEOUT,
            )
            compact = context.to_prompt_text()
        except asyncio.TimeoutError:
            logger.warning("ScreenReader.read_active_screen timed out")
            return {
                "status": "error",
                "detail": "I couldn't read the screen in time.",
                "skill": self.__class__.__name__,
            }
        except Exception as exc:
            logger.exception("ScreenReader.read_active_screen failed")
            return {
                "status": "error",
                "detail": "I encountered an error while reading the screen.",
                "skill": self.__class__.__name__,
            }

        # Ask the LLM to produce a short spoken description
        try:
            llm_response = await self._llm_manager.process(
                text="Describe what is on the screen in a short sentence suitable for speech.",
                context={"extra_context": compact},
            )
            summary = llm_response.response_text.strip()
            if not summary:
                summary = "I could not determine what is on the screen."
        except Exception as exc:
            logger.exception("ScreenSkill LLM summarisation failed")
            summary = "I encountered an error while reading the screen."

        return {"status": "ok", "detail": summary, "skill": self.__class__.__name__}


registry.register(ScreenSkill())