"""
Nova Brain – high-level façade for user text processing.
Delegates to AgentOrchestrator for intent parsing and skill execution.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova.agent import get_agent_orchestrator
    from nova.llm.manager import LLMManager

from nova.events import get_event_bus, IntentResolvedEvent, UserCommandReceivedEvent, GoalCompletedEvent

logger = logging.getLogger("nova.brain")


# -------------------------------------------------------------------------
# Public Brain class
# -------------------------------------------------------------------------
class Brain:
    """
    High-level façade:
        brain.process(user_text)  -> execution result dict
    """

    def __init__(self, llm_manager: Optional["LLMManager"] = None) -> None:
        # Import lazily to avoid circular import
        from nova.agent import get_agent_orchestrator
        from nova.llm.manager import get_llm_manager
        
        self._llm_manager = llm_manager or get_llm_manager()
        self._orchestrator = get_agent_orchestrator()
        self._event_bus = get_event_bus()
        self._conversation_context = ""  # could be extended for multi-turn

    # -----------------------------------------------------------------
    def process(self, user_text: str) -> Dict[str, Any]:
        """
        Full pipeline: user text -> AgentOrchestrator -> result.
        """
        # 1. Emit user command event
        self._event_bus.publish(UserCommandReceivedEvent(source="brain", payload={"text": user_text}))

        # 2. Delegate to AgentOrchestrator (handles LLM, parsing, skills, plans)
        context = {"conversation": self._conversation_context} if self._conversation_context else {}
        result = self._orchestrator.run(user_text, context=context)

        # 3. Update simple conversation context
        summary = result.get("summary") or result.get("result", {}).get("detail", "") if isinstance(result.get("result"), dict) else ""
        self._conversation_context = f"User: {user_text}\nAssistant: {summary}"

        # 4. Emit completion event
        self._event_bus.publish(
            GoalCompletedEvent(
                source="brain",
                payload={"goal_id": "", "summary": summary},
            )
        )

        return result


# -------------------------------------------------------------------------
# Convenience function used by existing entry points
# -------------------------------------------------------------------------
_brain_instance: Optional[Brain] = None


def get_brain() -> Brain:
    global _brain_instance
    if _brain_instance is None:
        _brain_instance = Brain()
    return _brain_instance