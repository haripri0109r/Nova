from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, validator


class Action(str, Enum):
    INCREASE = "increase"
    DECREASE = "decrease"
    SET = "set"
    OPEN = "open"
    CLOSE = "close"
    TOGGLE = "toggle"
    READ = "read"


class Amount(str, Enum):
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"


class IntentBase(BaseModel):
    """Common fields for every intent."""
    intent: str = Field(..., description="High‑level domain, e.g. set_volume")
    action: Action
    confidence: float = Field(..., ge=0.0, le=1.0)
    # Additional fields for compatibility with brain schema
    domain: Optional[str] = None
    operation: Optional[str] = None
    reason: str = ""
    source: str = "intent_engine"
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class VolumeIntent(IntentBase):
    intent: Literal["set_volume"] = "set_volume"
    amount: Optional[Amount] = None          # required when action is increase/decrease
    level: Optional[int] = Field(None, ge=0, le=100)   # required when action == SET


class BrightnessIntent(IntentBase):
    intent: Literal["set_brightness"] = "set_brightness"
    amount: Optional[Amount] = None
    level: Optional[int] = Field(None, ge=0, le=100)


class AppIntent(IntentBase):
    intent: Literal["open_application", "close_application"] = "open_application"
    application: str                         # e.g. "Visual Studio Code"


class ScreenReadIntent(IntentBase):
    intent: Literal["screen.read"] = "screen.read"
    action: Action = Action.READ


# Discriminated union – the router works with this single type
Intent = VolumeIntent | BrightnessIntent | AppIntent | ScreenReadIntent


def parse_intent(raw: dict) -> Intent:
    """Validate *raw* dict coming from the LLM and return a concrete Intent."""
    # Try each concrete model until one validates.
    for model in (ScreenReadIntent, VolumeIntent, BrightnessIntent, AppIntent):
        try:
            return model.parse_obj(raw)
        except ValidationError:
            continue
    # If none matched, raise the last error
    raise ValidationError(f"No intent model matched: {raw}")