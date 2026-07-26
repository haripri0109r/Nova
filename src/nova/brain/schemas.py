"""
Unified intent schema for Nova Brain.
All intents flowing through the system must conform to this schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, validator


class IntentParameters(BaseModel):
    """Dynamic parameters for an operation. Keys are operation‑specific."""
    # Example keys: amount, level, application, url, query, path, etc.
    # All values are kept as generic types; controllers will validate.
    class Config:
        extra = "allow"


class Intent(BaseModel):
    """Canonical intent representation used by the whole pipeline."""
    domain: str = Field(..., description="High‑level domain, e.g. 'audio'")
    operation: str = Field(..., description="Operation inside the domain, e.g. 'volume'")
    action: str = Field(..., description="Action to perform, e.g. 'decrease'")
    parameters: IntentParameters = Field(default_factory=IntentParameters)
    confidence: float = Field(..., ge=0.0, le=1.0, description="Model confidence 0‑1")
    reason: str = Field(default="", description="Human‑readable justification")
    source: str = Field(default="brain", description="Origin: 'brain' | 'legacy'")
    timestamp: datetime = Field(default_factory=datetime.utcnow)

    @validator("confidence")
    def _conf_range(cls, v: float) -> float:
        if not 0.0 <= v <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return v


class Plan(BaseModel):
    """A sequence of intents that together fulfil a higher‑level request."""
    intents: List[Intent]
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Clarification(BaseModel):
    """Returned when confidence is in the clarification band."""
    message: str
    suggested_intent: Optional[Intent] = None