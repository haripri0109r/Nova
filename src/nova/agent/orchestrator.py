"""
Agent Orchestrator – central coordinator for Nova.
Routes user input through Intent Engine → Skill Manager → Events/Workflows.
"""
from __future__ import annotations

import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from nova.brain.schemas import Plan
else:
    from nova.brain.schemas import Plan

from nova.events import get_event_bus
from nova.events.events import (
    UserCommandReceivedEvent,
    IntentResolvedEvent,
    GoalCompletedEvent,
    GoalFailedEvent,
)
from nova.intent.engine import get_intent_engine
from nova.intent.schema import VolumeIntent, BrightnessIntent, AppIntent, Intent as IntentSchema
from nova.skills.manager import get_skill_manager

logger = logging.getLogger("nova.agent.orchestrator")


class AgentOrchestrator:
    """
    Main orchestration pipeline:
    1. Receive user text
    2. Parse into Intent/Plan via IntentEngine
    3. Emit IntentResolvedEvent
    4. If confidence < threshold → return clarification
    5. If single Intent → execute via SkillManager
    6. If Plan (multiple intents) → execute via PlanExecutor (Workflows)
    7. Emit GoalCompleted/GoalFailed event
    8. Return result
    """

    def __init__(
        self,
        intent_engine: Optional[Any] = None,
        skill_manager: Optional[Any] = None,
        event_bus: Optional[Any] = None,
        confidence_threshold: float = 0.75,
    ) -> None:
        self._intent_engine = intent_engine or get_intent_engine()
        self._skill_manager = skill_manager or get_skill_manager()
        self._event_bus = event_bus or get_event_bus()
        self._confidence_threshold = confidence_threshold

    def run(self, user_text: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Full pipeline: user text → result dict.
        Returns dict with status, result, and metadata.
        """
        start_time = time.perf_counter()

        # 1. Emit user command event
        self._event_bus.publish(
            UserCommandReceivedEvent(
                source="agent",
                payload={"text": user_text, "context": context or {}},
            )
        )

        # 2. Parse intent/plan
        logger.debug("Parsing user text: %s", user_text)
        parsed = self._intent_engine.parse(user_text)

        # 3. Handle parsing result
        if isinstance(parsed, Plan):
            return self._execute_plan(parsed, user_text, start_time, context)
        elif isinstance(parsed, (VolumeIntent, BrightnessIntent, AppIntent)):
            return self._execute_intent(parsed, user_text, start_time, context)
        else:
            logger.warning("Unknown parse result type: %s", type(parsed))
            return self._error_result("Unable to parse intent", start_time)

    def _execute_intent(
        self,
        intent: "IntentSchema",
        user_text: str,
        start_time: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a single intent via SkillManager."""
        # Emit intent resolved event
        intent_name = self._get_intent_name(intent)
        self._event_bus.publish(
            IntentResolvedEvent(
                source="agent",
                payload={
                    "intent": intent_name,
                    "action": intent.action,
                    "confidence": intent.confidence,
                    "parameters": self._extract_parameters(intent),
                },
            )
        )

        # Confidence check
        if intent.confidence < self._confidence_threshold:
            logger.info(
                "Intent %s confidence %.2f < %.2f – requesting clarification",
                intent_name,
                intent.confidence,
                self._confidence_threshold,
            )
            return {
                "status": "clarify",
                "message": "I'm not sure I understood. Could you rephrase?",
                "confidence": intent.confidence,
                "intent": intent_name,
            }

        # Convert to dict for SkillManager
        intent_data = self._intent_to_dict(intent)

        # Execute via SkillManager
        logger.debug("Executing intent: %s", intent_name)
        skill_result = self._skill_manager.execute_intent(intent_data)

        elapsed = time.perf_counter() - start_time

        if skill_result.get("status") == "ok":
            result = {
                "status": "completed",
                "result": skill_result.get("result"),
                "skill": skill_result.get("skill"),
                "elapsed_ms": round(elapsed * 1000, 2),
                "intent": intent_name,
            }
            self._event_bus.publish(
                GoalCompletedEvent(
                    source="agent",
                    payload={"goal_id": "", "summary": str(skill_result.get("result", ""))},
                )
            )
        else:
            result = {
                "status": "error",
                "message": skill_result.get("message", "Skill execution failed"),
                "elapsed_ms": round(elapsed * 1000, 2),
                "intent": intent_name,
            }
            self._event_bus.publish(
                GoalFailedEvent(
                    source="agent",
                    payload={"goal_id": "", "reason": skill_result.get("message", "Unknown error")},
                )
            )

        return result

    def _execute_plan(
        self,
        plan: Plan,
        user_text: str,
        start_time: float,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a multi-intent plan via PlanExecutor (Workflows)."""
        from .plan_executor import PlanExecutor

        # Emit intent resolved for first intent (for logging)
        first_intent = plan.intents[0] if plan.intents else None
        if first_intent:
            first_intent_name = self._get_intent_name(first_intent)
            self._event_bus.publish(
                IntentResolvedEvent(
                    source="agent",
                    payload={
                        "intent": first_intent_name,
                        "action": first_intent.action,
                        "confidence": first_intent.confidence,
                        "parameters": self._extract_parameters(first_intent),
                        "is_plan": True,
                        "plan_length": len(plan.intents),
                    },
                )
            )

        # Execute plan via PlanExecutor
        executor = PlanExecutor(skill_manager=self._skill_manager, event_bus=self._event_bus)
        try:
            result = executor.execute(plan, user_text, context or {})
        except Exception as e:
            logger.exception("Plan execution failed")
            result = {
                "status": "error",
                "message": f"Plan execution failed: {e}",
                "elapsed_ms": round((time.perf_counter() - start_time) * 1000, 2),
            }
            self._event_bus.publish(
                GoalFailedEvent(
                    source="agent",
                    payload={"goal_id": "", "reason": str(e)},
                )
            )
            return result

        elapsed = time.perf_counter() - start_time

        if result.get("status") == "completed":
            self._event_bus.publish(
                GoalCompletedEvent(
                    source="agent",
                    payload={"goal_id": "", "summary": str(result.get("result", ""))},
                )
            )
        else:
            self._event_bus.publish(
                GoalFailedEvent(
                    source="agent",
                    payload={"goal_id": "", "reason": result.get("message", "Plan failed")},
                )
            )

        result["elapsed_ms"] = round(elapsed * 1000, 2)
        return result

    def _extract_parameters(self, intent: Any) -> Dict[str, Any]:
        """Extract parameters from intent (works with both brain.schemas.Intent and intent.schema types)."""
        # brain.schemas.Intent has a parameters field
        if hasattr(intent, 'parameters') and intent.parameters:
            params = intent.parameters
            if hasattr(params, 'dict'):
                return params.dict()
            elif hasattr(params, 'model_dump'):
                return params.model_dump()
            else:
                return dict(params)

        # intent.schema types (VolumeIntent, BrightnessIntent, AppIntent) have individual fields
        params = {}
        for field in ['amount', 'level', 'application']:
            if hasattr(intent, field):
                value = getattr(intent, field)
                if value is not None:
                    params[field] = value
        return params

    def _get_intent_name(self, intent: Any) -> str:
        """Get intent name from any intent type (brain.schemas.Intent or intent.schema types)."""
        # brain.schemas.Intent has 'intent' field (for backwards compatibility)
        if hasattr(intent, 'intent') and intent.intent:
            return intent.intent
        # brain.schemas.Intent has domain + operation - construct intent name
        if hasattr(intent, 'domain') and hasattr(intent, 'operation'):
            return f"{intent.domain}_{intent.operation}"
        # intent.schema types (VolumeIntent, BrightnessIntent, AppIntent) have 'intent' as literal
        # but it might be stored in __pydantic_extra__
        if hasattr(intent, '__pydantic_extra__') and intent.__pydantic_extra__:
            return intent.__pydantic_extra__.get('intent', 'unknown')
        # Fallback: construct from class name
        return intent.__class__.__name__.replace('Intent', '').lower()

    def _intent_to_dict(self, intent: Any) -> Dict[str, Any]:
        """Convert Intent Pydantic model to dict for SkillManager."""
        data = intent.dict()
        # Flatten parameters - works for both brain.schemas.Intent and intent.schema types
        if "parameters" in data and data["parameters"]:
            params = data.pop("parameters")
            if hasattr(params, "dict"):
                params = params.dict()
            elif hasattr(params, "model_dump"):
                params = params.model_dump()
            data.update(params)
        else:
            # intent.schema types (VolumeIntent, BrightnessIntent, AppIntent) have fields directly
            # They are already in data, just need to handle enums
            for key, value in list(data.items()):
                if hasattr(value, 'value'):  # Enum
                    data[key] = value.value
        # Ensure 'intent' field is present for SkillManager (required field)
        # Use computed intent name, not the raw field which may be missing/empty
        data["intent"] = self._get_intent_name(intent)
        return data

    def _error_result(self, message: str, start_time: float) -> Dict[str, Any]:
        elapsed = time.perf_counter() - start_time
        return {
            "status": "error",
            "message": message,
            "elapsed_ms": round(elapsed * 1000, 2),
        }


# Global singleton
_orchestrator_instance: Optional[AgentOrchestrator] = None


def get_agent_orchestrator() -> AgentOrchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = AgentOrchestrator()
    return _orchestrator_instance