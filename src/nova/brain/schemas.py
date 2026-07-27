"""
Unified intent schema for Nova Brain.
All intents flowing through the system must conform to this schema.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, validator

# Import the canonical Intent from intent.schema
from nova.intent.schema import Intent


class IntentParameters(BaseModel):
    """Dynamic parameters for an operation. Keys are operation‑specific."""
    # Example keys: amount, level, application, url, query, path, etc.
    # All values are kept as generic types; controllers will validate.
    class Config:
        extra = "allow"


class Plan(BaseModel):
    """A sequence of intents that together fulfil a higher‑level request."""
    intents: List[Intent]
    description: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Clarification(BaseModel):
    """Returned when confidence is in the clarification band."""
    message: str
    suggested_intent: Optional[Intent] = None