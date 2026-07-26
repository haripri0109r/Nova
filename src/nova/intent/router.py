from __future__ import annotations

import logging
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from nova.agent import get_agent_orchestrator

from .schema import Intent

log = logging.getLogger("nova.intent.router")


class IntentRouter:
    """
    Routes a validated Intent through the Agent Orchestrator which uses
    the SkillManager to execute the appropriate skill.
    """

    def __init__(self) -> None:
        self._orchestrator = None

    def _get_orchestrator(self):
        if self._orchestrator is None:
            from nova.agent import get_agent_orchestrator
            self._orchestrator = get_agent_orchestrator()
        return self._orchestrator

    def route(self, intent: Intent) -> Dict[str, Any]:
        # Confidence guard – clarification path
        if intent.confidence < 0.75:
            log.info(
                "Intent %s confidence %.2f < 0.75 – asking user for clarification",
                intent.intent,
                intent.confidence,
            )
            return {"status": "clarify", "message": "I'm not sure I understood. Could you re‑phrase?"}

        # Delegate to Agent Orchestrator
        try:
            # Build a minimal user-text representation for the orchestrator.
            # The orchestrator expects raw user text; we synthesize a short description.
            user_text = f"[{intent.intent}] {intent.action} {intent.parameters}"
            result = self._get_orchestrator().run(user_text)
            log.debug("Orchestrator returned: %s", result)
            return result
        except Exception:  # pragma: no cover
            log.exception("Orchestrator execution failed for intent %s", intent.intent)
            return {"status": "error", "message": "Internal error while executing the command."}


# Backwards compatibility alias
SkillRouter = IntentRouter


# ----------------------------------------------------------------------
# Convenience – Nova can keep its old `route_intent(text)` call
# ----------------------------------------------------------------------
from .engine import get_intent_engine

_intent_engine = get_intent_engine()


def route_intent(user_text: str, executor: Any = None) -> Dict[str, Any]:
    """
    One‑shot helper used by the current Nova entry‑point.
    The `executor` argument is kept for backward compatibility but is ignored.
    """
    intent = _intent_engine.parse(user_text)
    router = IntentRouter()
    return router.route(intent)