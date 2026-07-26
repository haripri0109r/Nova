from __future__ import annotations

import logging
from typing import Any, Dict

from .schema import Intent
from nova.brain import get_brain

log = logging.getLogger("nova.intent.router")


class IntentRouter:
    """
    Routes a validated Intent through the Nova Brain which in turn uses the
    ControllerManager to execute the appropriate controller.
    """

    def __init__(self) -> None:
        self._brain = get_brain()

    def route(self, intent: Intent) -> Dict[str, Any]:
        # Confidence guard – clarification path
        if intent.confidence < 0.75:
            log.info(
                "Intent %s confidence %.2f < 0.75 – asking user for clarification",
                intent.intent,
                intent.confidence,
            )
            return {"status": "clarify", "message": "I’m not sure I understood. Could you re‑phrase?"}

        # Delegate to Brain (which forwards to ControllerManager)
        try:
            # Build a minimal user‑text representation for the brain.
            # The brain expects raw user text; we synthesize a short description.
            user_text = f"[{intent.domain}] {intent.operation} {intent.action}"
            result = self._brain.process(user_text)
            log.debug("Brain returned: %s", result)
            return result
        except Exception:  # pragma: no cover
            log.exception("Brain execution failed for intent %s", intent.intent)
            return {"status": "error", "message": "Internal error while executing the command."}


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