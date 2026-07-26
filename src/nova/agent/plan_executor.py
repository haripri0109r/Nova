"""
PlanExecutor – executes a multi-intent Plan by running each intent sequentially.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from nova.brain.schemas import Plan

from nova.events import get_event_bus
from nova.events.events import IntentResolvedEvent
from nova.skills.manager import get_skill_manager

logger = logging.getLogger("nova.agent.plan_executor")


def _get_intent_name(intent: Any) -> str:
    """Get intent name from any intent type (brain.schemas.Intent or intent.schema types)."""
    # brain.schemas.Intent has 'intent' field
    if hasattr(intent, 'intent') and intent.intent:
        return intent.intent
    # brain.schemas.Intent has domain + operation - construct intent name
    if hasattr(intent, 'domain') and hasattr(intent, 'operation'):
        return f"{intent.domain}_{intent.operation}"
    # intent.schema types (VolumeIntent, BrightnessIntent, AppIntent) have 'intent' as literal
    if hasattr(intent, '__pydantic_extra__') and intent.__pydantic_extra__:
        return intent.__pydantic_extra__.get('intent', 'unknown')
    # Fallback: construct from class name
    return intent.__class__.__name__.replace('Intent', '').lower()


def _extract_parameters(intent: Any) -> Dict[str, Any]:
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


class PlanExecutor:
    """
    Executes a Plan (sequence of intents) with proper error handling,
    event emission, and step tracking.
    """

    def __init__(
        self,
        skill_manager=None,
        event_bus=None,
    ) -> None:
        self._skill_manager = skill_manager or get_skill_manager()
        self._event_bus = event_bus or get_event_bus()

    def _intent_to_dict(self, intent: Any) -> Dict[str, Any]:
        """Convert Pydantic Intent to dict for SkillManager."""
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
            # intent.schema types have fields directly
            for key, value in list(data.items()):
                if hasattr(value, 'value'):  # Enum
                    data[key] = value.value
        # Ensure 'intent' field is present for SkillManager (required field)
        if "intent" not in data:
            data["intent"] = _get_intent_name(intent)
        return data

    def execute(
        self,
        plan: "Plan",
        user_text: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute all intents in the plan sequentially.
        Returns a result dict with status, steps, and final result.
        """
        context = context or {}
        steps: List[Dict[str, Any]] = []
        start_time = time.perf_counter()

        logger.info("Executing plan: %s (%d intents)", plan.description or "Unnamed plan", len(plan.intents))

        for i, intent in enumerate(plan.intents):
            step_start = time.perf_counter()
            intent_name = _get_intent_name(intent)
            logger.debug("Step %d/%d: %s (confidence=%.2f)", i + 1, len(plan.intents), intent_name, intent.confidence)

            # Emit intent resolved event for tracking
            self._event_bus.publish(
                IntentResolvedEvent(
                    source="plan_executor",
                    payload={
                        "intent": intent_name,
                        "action": intent.action,
                        "confidence": intent.confidence,
                        "parameters": _extract_parameters(intent),
                    },
                )
            )

            # Convert intent to skill input format
            intent_data = self._intent_to_dict(intent)

            # Merge context into intent data
            intent_data["_context"] = context

            # Execute via skill manager
            skill_result = self._skill_manager.execute_intent(intent_data)

            step_elapsed = time.perf_counter() - step_start
            step_record = {
                "step": i + 1,
                "intent": intent_name,
                "action": intent.action,
                "confidence": intent.confidence,
                "skill_result": skill_result,
                "elapsed_ms": round(step_elapsed * 1000, 2),
            }
            steps.append(step_record)

            # Check if step failed
            if skill_result.get("status") != "ok":
                logger.warning("Step %d failed: %s", i + 1, skill_result)
                return {
                    "status": "error",
                    "message": f"Step {i + 1} ({intent_name}) failed: {skill_result.get('message', 'Unknown error')}",
                    "steps": steps,
                    "failed_at_step": i + 1,
                }

            # Update context with step result for subsequent steps
            if "result" in skill_result:
                context[f"step_{i + 1}_result"] = skill_result["result"]

        total_elapsed = time.perf_counter() - start_time
        logger.info("Plan completed in %.3fs (%d steps)", total_elapsed, len(steps))

        return {
            "status": "completed",
            "result": steps[-1].get("skill_result", {}).get("result") if steps else None,
            "steps": steps,
            "total_elapsed_ms": round(total_elapsed * 1000, 2),
        }