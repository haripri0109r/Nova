"""
Nova Brain – high-level façade for user text processing.
Delegates to AgentOrchestrator for intent parsing and skill execution.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova.agent import get_agent_orchestrator

from nova.events import get_event_bus, IntentResolvedEvent, UserCommandReceivedEvent, GoalCompletedEvent

logger = logging.getLogger("nova.brain")

# -------------------------------------------------------------------------
# Configuration – all via env vars with sensible defaults
# -------------------------------------------------------------------------
MODEL_PATH = os.getenv(
    "NOVA_BRAIN_MODEL",
    "models/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf",
)
CTX_SIZE = int(os.getenv("NOVA_BRAIN_CTX", "2048"))
N_THREADS = int(os.getenv("NOVA_BRAIN_THREADS", str(os.cpu_count() or 4)))
N_GPU_LAYERS = int(os.getenv("NOVA_BRAIN_GPU_LAYERS", "0"))
TEMPERATURE = float(os.getenv("NOVA_BRAIN_TEMP", "0.0"))  # deterministic


# -------------------------------------------------------------------------
# Public Brain class
# -------------------------------------------------------------------------
class Brain:
    """
    High-level façade:
        brain.process(user_text)  -> execution result dict
    """

    def __init__(self) -> None:
        # Import lazily to avoid circular import
        from nova.agent import get_agent_orchestrator
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