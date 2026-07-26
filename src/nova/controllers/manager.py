"""
ControllerManager – bridges the intent router to domain controllers.
"""

import logging
from typing import Any, Dict, Optional

from .registry import registry
from nova.events import get_event_bus, GoalCompletedEvent, GoalFailedEvent, UserCommandReceivedEvent

logger = logging.getLogger("nova.controllers.manager")


class ControllerManager:
    """
    Receives a validated intent dict, finds the appropriate controller,
    executes the operation and returns a structured result.
    """

    def __init__(self) -> None:
        self._registry = registry
        self._event_bus = get_event_bus()

    def execute_intent(self, intent: Dict[str, Any]) -> Dict[str, Any]:
        """
        Main entry point called by the router.

        Expected intent keys:
            - domain (str)
            - operation (str)
            - action (str)   # e.g. increase / decrease / enable
            - amount / level / other parameters as needed
            - confidence (float)

        Returns a dict:
            {
                "status": "ok" | "error" | "not_found",
                "detail": "...",
                "controller": "<ControllerClassName>",
            }
        """
        domain = intent.get("domain")
        if not domain:
            logger.error("Intent missing 'domain' field: %s", intent)
            return {"status": "error", "detail": "Missing domain in intent"}

        controller = self._registry.get(domain)
        if controller is None:
            logger.warning("No controller registered for domain %r", domain)
            return {"status": "not_found", "detail": f"No controller for domain {domain}"}

        # Optional confidence gate – the router may already enforce it,
        # but we keep a safety net.
        confidence = intent.get("confidence", 1.0)
        if confidence < 0.75:
            logger.info(
                "Intent confidence %.2f below threshold for domain %s – refusing execution",
                confidence,
                domain,
            )
            return {"status": "error", "detail": "Low confidence; clarification required"}

        logger.info("Executing intent %s via %s", intent, controller)
        try:
            # Guard: ensure controller declares it can handle
            if not controller.can_handle(intent):
                logger.warning("Controller %s declined intent %s", controller, intent)
                return {"status": "error", "detail": f"Controller {controller} cannot handle intent"}

            # Emit pre‑execution event
            self._event_bus.publish(
                UserCommandReceivedEvent(
                    source="controller_manager",
                    payload={"domain": domain, "operation": intent.get("operation")},
                )
            )

            result = controller.execute(intent)
            logger.debug("Controller %s returned: %s", controller, result)

            # Emit success event
            self._event_bus.publish(
                GoalCompletedEvent(
                    source="controller_manager",
                    payload={"goal_id": f"{domain}.{intent.get('operation')}", "summary": str(result)},
                )
            )

            # Normalise result
            if not isinstance(result, dict):
                result = {"status": "ok", "detail": str(result)}
            result.setdefault("controller", controller.__class__.__name__)
            return result
        except Exception:
            logger.exception("Controller %s raised an exception", controller)
            self._event_bus.publish(
                GoalFailedEvent(
                    source="controller_manager",
                    payload={"goal_id": f"{domain}.{intent.get('operation')}", "reason": "Controller exception"},
                )
            )
            return {"status": "error", "detail": "Controller execution failed"}


# Global singleton
_manager: ControllerManager | None = None


def get_controller_manager() -> ControllerManager:
    """Return the process‑wide ControllerManager instance."""
    global _manager
    if _manager is None:
        _manager = ControllerManager()
    return _manager