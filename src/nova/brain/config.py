"""
Brain Engine configuration types.
"""
from __future__ import annotations
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field


class IntentClassifierConfig(BaseModel):
    provider: str = "placeholder"
    model_path: Optional[str] = None
    confidence_threshold: float = Field(default=0.5, ge=0.0, le=1.0)
    extra: Dict[str, Any] = Field(default_factory=dict)


class PlannerConfig(BaseModel):
    provider: str = "placeholder"
    model: Optional[str] = None
    max_steps: int = 10
    extra: Dict[str, Any] = Field(default_factory=dict)


class RouterConfig(BaseModel):
    provider: str = "placeholder"
    extra: Dict[str, Any] = Field(default_factory=dict)


class BrainEngineConfig(BaseModel):
    intent_classifier: IntentClassifierConfig = Field(default_factory=IntentClassifierConfig)
    planner: PlannerConfig = Field(default_factory=PlannerConfig)
    router: RouterConfig = Field(default_factory=RouterConfig)
    auto_initialize: bool = True