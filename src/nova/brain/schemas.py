"""
Compatibility schemas for Brain Engine – re-exports core models for downstream consumers.
"""
from .models import ExecutionPlan, PlanStep, IntentResult, RecognizedInput, BrainResponse, BrainDecision, BrainHealth
from pydantic import BaseModel
from typing import Any, Dict, Optional

# Alias for backward compatibility
Plan = ExecutionPlan

class IntentParameters(BaseModel):
    """Structured parameters extracted from an intent."""
    action: Optional[str] = None
    target: Optional[str] = None
    parameters: Dict[str, Any] = {}
    confidence: float = 1.0

__all__ = [
    "Plan",
    "ExecutionPlan",
    "PlanStep",
    "IntentResult",
    "RecognizedInput",
    "BrainResponse",
    "BrainDecision",
    "BrainHealth",
    "IntentParameters",
]