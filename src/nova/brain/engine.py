"""
Brain Engine – high‑level orchestration of intent classification, agent orchestration,
skill execution and response generation.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from dataclasses import dataclass

from .models import (
    RecognizedInput,
    BrainResponse,
    ExecutionPlan,
    RoutingDecision,
    PlanStep,
    IntentResult,
)
from .types import IntentCategory, ConfidenceLevel
from .intent_classifier import (
    BaseIntentClassifier,
    create_intent_classifier,
    IntentClassifierConfig,
)
from .adapter import (
    intent_to_execution_request,
    execution_request_to_plan_steps,
    execution_plan_to_execution_request,
)
from .planner import get_planner
from ..agent.orchestrator import AgentOrchestrator, get_agent_orchestrator
from ..agent.models import SkillContext, ExecutionContext, TaskAction, TaskCommand
from ..agent.task_command_router import get_task_command_router
from ..events import get_event_bus
from ..events.events import IntentResolvedEvent, GoalCompletedEvent, GoalFailedEvent
from .exceptions import BrainEngineError

logger = logging.getLogger("nova.brain.engine")


@dataclass
class BrainEngineConfig:
    intent_classifier: Optional[IntentClassifierConfig] = None
    auto_start: bool = True


class BrainEngine:
    """
    Central brain of Nova – receives raw recognized text, classifies intent,
    builds an execution plan, dispatches to agents/skills, and composes a response.
    """

    def __init__(self, config: Optional["BrainEngineConfig"] = None):
        self.config = config or BrainEngineConfig()
        self._intent_classifier = None
        self._orchestrator = None
        self._skill_manager = None
        self._event_bus = None
        self._initialized = False

    async def initialize(self) -> bool:
        if self._initialized:
            return True

        logger.info("Initializing Brain Engine...")

        try:
            # Intent classifier
            ic_cfg = self.config.intent_classifier or IntentClassifierConfig()
            self._intent_classifier = create_intent_classifier(ic_cfg)
            await self._intent_classifier.initialize()

            # Agent orchestrator (lazy import to avoid circular)
            from ..agent.orchestrator import AgentOrchestrator, get_agent_orchestrator
            self._orchestrator = get_agent_orchestrator()
            await self._orchestrator.initialize()

            # Skill manager (lazy import)
            from ..skills.manager import get_skill_manager
            self._skill_manager = get_skill_manager()
            await self._skill_manager.initialize()

            # Event bus
            self._event_bus = get_event_bus()

            self._initialized = True
            logger.info("Brain Engine initialized successfully")
            return True

        except Exception as exc:
            logger.error(f"Brain Engine initialization failed: {exc}")
            raise BrainEngineError(f"Initialization failed: {exc}") from exc

    async def cleanup(self) -> None:
        if self._intent_classifier:
            await self._intent_classifier.cleanup()
        if self._orchestrator:
            await self._orchestrator.cleanup()
        if self._skill_manager:
            await self._skill_manager.cleanup()
        self._initialized = False
        logger.info("Brain Engine cleaned up")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def process_text(self, text: str, session_id: Optional[str] = None) -> "BrainResponse":
        """
        Main entry point – turn raw user text into a structured BrainResponse.
        """
        if not self._initialized:
            await self.initialize()

        start = datetime.utcnow()

        # 1️⃣ Recognized input
        recognized = RecognizedInput(
            text=text,
            session_id=session_id,
            timestamp=datetime.utcnow(),
        )

        # 2️⃣ Intent classification
        intent = await self._intent_classifier.classify(RecognizedInput(text=text, session_id=session_id))
        logger.debug(f"Intent classified: {intent.category.value} ({intent.confidence:.2f})")

        # Emit intent resolved event
        self._event_bus.publish(
            IntentResolvedEvent(
                source="brain_engine",
                payload={"intent": intent.category.value, "confidence": intent.confidence},
            )
        )

        # ⚡ Fast path: TASK_CONTROL and TASK_QUERY bypass Planner, LLM, and skill manager
        if intent.category in (IntentCategory.TASK_CONTROL, IntentCategory.TASK_QUERY):
            default_action = TaskAction.STATUS if intent.category == IntentCategory.TASK_QUERY else None
            command = TaskCommand.from_entities(
                entities=intent.entities,
                session_id=session_id or "default",
                default_action=default_action,
            )
            router = get_task_command_router()
            result = await router.route(command)

            routing = RoutingDecision(
                target="task_command_router",
                reason=f"Fast-path execution for {intent.category.value}",
                payload={"action": command.action.value, "success": result.success, "task_id": result.task_id},
            )
            plan = ExecutionPlan(description=f"Task command {command.action.value}")

            return BrainResponse(
                intent=intent,
                plan=plan,
                routing=routing,
                response_text=result.message,
                timestamp=datetime.utcnow(),
            )

        # 🛡️ Shutdown precondition and stateful workflow handling
        session = session_id or "default"
        from nova.brain.shutdown_workflow import (
            get_shutdown_workflow_manager,
            is_cancellation_phrase,
            is_continuation_phrase,
        )
        from nova.skills.system.app_detector import (
            check_shutdown_precondition,
            format_initial_blocked_message,
            format_still_open_message,
        )

        wf_mgr = get_shutdown_workflow_manager()

        if wf_mgr.is_pending(session):
            if is_cancellation_phrase(text):
                wf_mgr.clear_pending(session)
                elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
                return BrainResponse(
                    intent=intent,
                    plan=ExecutionPlan(steps=[], description="Shutdown cancelled"),
                    routing=RoutingDecision(target="brain_engine", reason="Shutdown cancelled by user"),
                    response_text="Okay, I won't shut down.",
                    timestamp=datetime.utcnow(),
                    processing_time_ms=elapsed_ms,
                    metadata={"success": True, "cancelled": True},
                )
            elif is_continuation_phrase(text) or intent.category == IntentCategory.SHUTDOWN:
                # Mandatory second check of real Windows application state
                precond = check_shutdown_precondition()
                if not precond["ready"]:
                    wf_mgr.update_pending(session, precond["open_applications"])
                    elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
                    msg = format_still_open_message(precond["open_applications"])
                    return BrainResponse(
                        intent=intent,
                        plan=ExecutionPlan(steps=[], description="Shutdown precondition blocked"),
                        routing=RoutingDecision(target="brain_engine", reason="Open applications remain"),
                        response_text=msg,
                        timestamp=datetime.utcnow(),
                        processing_time_ms=elapsed_ms,
                        metadata={"success": False, "open_applications": precond["open_applications"]},
                    )
                else:
                    # All user applications are closed. Clear workflow state and proceed to standard shutdown flow.
                    wf_mgr.clear_pending(session)
                    text = "shutdown"
                    intent = IntentResult(
                        category=IntentCategory.SHUTDOWN,
                        confidence=0.95,
                        confidence_level=ConfidenceLevel.HIGH,
                        entities={},
                        raw_scores={IntentCategory.SHUTDOWN.value: 0.95},
                    )
            else:
                # User asked an unrelated request; clear pending shutdown so it doesn't hijack future requests
                wf_mgr.clear_pending(session)

        elif intent.category == IntentCategory.SHUTDOWN:
            # Initial shutdown request: inspect currently open user applications
            precond = check_shutdown_precondition()
            if not precond["ready"]:
                wf_mgr.set_pending(session, precond["open_applications"])
                elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)
                msg = format_initial_blocked_message(precond["open_applications"])
                return BrainResponse(
                    intent=intent,
                    plan=ExecutionPlan(steps=[], description="Shutdown precondition blocked"),
                    routing=RoutingDecision(target="brain_engine", reason="Open applications detected"),
                    response_text=msg,
                    timestamp=datetime.utcnow(),
                    processing_time_ms=elapsed_ms,
                    metadata={"success": False, "open_applications": precond["open_applications"]},
                )

        # 3️⃣ Generate multi-step plan using Planner
        planner = get_planner()
        await planner.initialize()
        
        # Detect if request likely needs multi-step planning
        # Simple heuristic: check for conjunctions suggesting multiple actions
        multi_step_keywords = [" and ", " then ", " after ", " followed by ", " then ", ", "]
        needs_multi_step = any(kw in text.lower() for kw in multi_step_keywords)
        
        # Get existing context if any (for multi-turn conversations)
        # Pass context to planner to force LLM path for likely multi-step requests
        context = {"potentially_multi_step": True} if needs_multi_step else None
        
        plan = await planner.plan(text, intent, context)
        
        # 4️⃣ Convert plan to Agent ExecutionRequest
        request = execution_plan_to_execution_request(plan, session_id)

        # 5️⃣ Create ExecutionContext for multi-step tracking with unique execution_id
        from uuid import uuid4
        exec_id = uuid4().hex
        execution_context = ExecutionContext(
            session_id=session_id or "default",
            execution_id=exec_id,
            task_id=exec_id,
            metadata={"user_text": text, "intent": intent.category.value},
        )

        # 6️⃣ Execute via Agent Orchestrator with context
        execution_result = await self._orchestrator.execute_with_context(request, execution_context)


        # 7️⃣ Compose response text - concatenate all step details
        response_text = self._compose_multi_step_response(execution_result)

        # 8️⃣ Build brain‑level ExecutionPlan for the response
        brain_plan = ExecutionPlan(steps=plan.steps, description=plan.description)

        # Routing decision
        routing = RoutingDecision(
            target="agent_orchestrator",
            reason="Routed to agent orchestrator for skill execution",
            payload={"plan_id": brain_plan.steps[0].id if brain_plan.steps else None},
        )

        # Emit completion event
        if execution_result.success:
            self._event_bus.publish(
                GoalCompletedEvent(source="brain_engine", payload={"result": {"success": True, "message": response_text}})
            )
        else:
            self._event_bus.publish(
                GoalFailedEvent(source="brain_engine", payload={"error": execution_result.message})
            )

        elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        return BrainResponse(
            intent=intent,
            plan=brain_plan,
            routing=routing,
            response_text=response_text,
            timestamp=datetime.utcnow(),
            processing_time_ms=elapsed_ms,
            metadata={
                "success": execution_result.success,
                "execution_id": execution_result.execution_id or exec_id,
                "task_id": execution_result.execution_id or exec_id,
            },
        )

    def _compose_response(self, intent, execution_result: Dict[str, Any]) -> str:
        """Very small templating – replace with NLG later."""
        if execution_result.get("success"):
            message = execution_result.get("message", "")
            skill_detail = execution_result.get("skill_detail")
            if skill_detail:
                return f"Done. {skill_detail}"
            return f"Done. {message}"
        return f"Sorry, I couldn't complete that. {execution_result.get('error','')}"

    def _compose_multi_step_response(self, execution_result: "ExecutionResult") -> str:
        """Compose response from multi-step execution result."""
        if not execution_result.success:
            if execution_result.message and execution_result.message.startswith("Confirmation required"):
                return execution_result.message
            return f"Sorry, I couldn't complete that. {execution_result.message}"
        
        # Collect all skill details from successful steps
        details = []
        for result in execution_result.results:
            if result.success and result.result and isinstance(result.result, dict):
                detail = result.result.get("detail")
                if detail:
                    details.append(detail)
        
        if details:
            return "Done. " + " ".join(details)
        
        return f"Done. {execution_result.message}"

    # ------------------------------------------------------------------
    # Backward‑compatible synchronous wrapper used by legacy entry points
    # ------------------------------------------------------------------
    def process(self, text: str) -> Dict[str, Any]:
        """
        Legacy façade – calls the async ``process_text`` and converts the
        ``BrainResponse`` into the plain‑dict shape the old code expects
        (keys: ``status``, ``message``, ``summary``).

        This method is safe to call from synchronous code **only when no
        event loop is currently running**. If a loop is running (e.g. inside
        an async context), a ``RuntimeError`` is raised with a clear message
        directing the caller to use ``await process_text(...)`` instead.
        """
        import asyncio

        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            # No current loop – create a new one for this call
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        if loop.is_running():
            raise RuntimeError(
                "Cannot call synchronous BrainEngine.process() while an event loop is running. "
                "Use 'await brain_engine.process_text(text)' from async code."
            )

        resp = loop.run_until_complete(self.process_text(text))
        status = "completed" if (hasattr(resp, "metadata") and resp.metadata.get("success", False)) else "error"
        return {
            "status": status,
            "message": resp.response_text,
            "summary": resp.response_text,
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def intent_classifier(self):
        return self._intent_classifier

    @property
    def orchestrator(self):
        return self._orchestrator

    @property
    def skill_manager(self):
        return self._skill_manager


# Global singleton
_brain_engine: Optional["BrainEngine"] = None


def get_brain_engine(config: Optional["BrainEngineConfig"] = None) -> BrainEngine:
    global _brain_engine
    if _brain_engine is None:
        _brain_engine = BrainEngine(config)
    return _brain_engine