"""
Brain Engine – high‑level orchestration of intent classification, agent orchestration,
skill execution and response generation.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .models import (
    RecognizedInput,
    BrainResponse,
    ExecutionPlan,
    RoutingDecision,
)
from .intent_classifier import (
    BaseIntentClassifier,
    create_intent_classifier,
    IntentClassifierConfig,
)
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

        # 3️⃣ Build execution plan via Agent Orchestrator
        plan: ExecutionPlan = await self._orchestrator.build_plan(intent, session_id)

        # 4️⃣ Execute plan (delegates to skills / agents)
        execution_result = await self._orchestrator.execute_plan(plan, session_id)

        # 5️⃣ Compose response text (simple templating for now)
        response_text = self._compose_response(intent, execution_result)

        # Routing decision (currently always agent_orchestrator)
        routing = RoutingDecision(
            target="agent_orchestrator",
            reason="Default routing to agent orchestrator",
            payload={"plan_id": plan.steps[0].id if plan.steps else None},
        )

        # Emit completion event
        if execution_result.get("success"):
            self._event_bus.publish(
                GoalCompletedEvent(source="brain_engine", payload={"result": execution_result})
            )
        else:
            self._event_bus.publish(
                GoalFailedEvent(source="brain_engine", payload={"error": execution_result.get("error")})
            )

        elapsed_ms = int((datetime.utcnow() - start).total_seconds() * 1000)

        return BrainResponse(
            intent=IntentResult(
                category=IntentCategory.GENERAL_CONVERSATION,  # placeholder; actual category from intent
                confidence=0.9,
                confidence_level=None,
                entities={},
                raw_scores={},
            ),
            plan=ExecutionPlan(steps=[]),
            routing=RoutingDecision(target="agent_orchestrator", reason="default"),
            response_text=response_text,
            timestamp=datetime.utcnow(),
            processing_time_ms=int((datetime.utcnow() - start).total_seconds() * 1000),
        )

    def _compose_response(self, intent, execution_result: Dict[str, Any]) -> str:
        """Very small templating – replace with NLG later."""
        if execution_result.get("success"):
            return f"Done. {execution_result.get('message','')}"
        return f"Sorry, I couldn't complete that. {execution_result.get('error','')}"

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