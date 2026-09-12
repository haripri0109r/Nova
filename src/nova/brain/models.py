"""
Brain Engine data models.
"""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .types import IntentCategory, ConfidenceLevel, ExecutionMode


class RecognizedInput(BaseModel):
    """Input coming from Voice Engine."""
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    language: str = "en"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class IntentResult(BaseModel):
    """Result of intent classification."""
    category: IntentCategory
    confidence: float = Field(ge=0.0, le=1.0)
    confidence_level: ConfidenceLevel
    entities: Dict[str, Any] = Field(default_factory=dict)
    raw_scores: Dict[str, float] = Field(default_factory=dict)


class PlanStep(BaseModel):
    """Single step in an execution plan."""
    id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex)
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[int] = Field(default_factory=list)  # indices of previous steps


class ExecutionPlan(BaseModel):
    """Full execution plan returned by planner."""
    steps: List[PlanStep] = Field(default_factory=list)
    intents: List[Any] = Field(default_factory=list)  # for backward compatibility with agent orchestrator
    description: str = ""  # optional description
    requires_llm: bool = False
    llm_prompt: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class RoutingDecision(BaseModel):
    """Decision where to send the request."""
    target: str  # e.g. "agent_orchestrator", "skill_manager"
    reason: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class BrainResponse(BaseModel):
    """Final structured response from Brain Engine."""
    intent: IntentResult
    plan: ExecutionPlan
    routing: RoutingDecision
    response_text: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    processing_time_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BrainDecision(BaseModel):
    """Legacy decision model (kept for compatibility)."""
    intent: IntentResult
    execution_mode: ExecutionMode
    plan: ExecutionPlan
    response_text: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    requires_llm: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BrainHealth(BaseModel):
    """Health status."""
    status: str
    intent_classifier: str = "ok"
    planner: str = "ok"
    router: str = "ok"
    last_check: datetime = Field(default_factory=datetime.utcnow)