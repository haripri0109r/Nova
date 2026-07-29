"""Typed configuration objects – pure Pydantic, no side‑effects."""
from __future__ import annotations
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field
from .types import LLMProvider


class LLMProviderConfig(BaseModel):
    """Per‑provider knobs – only the fields a provider actually needs."""
    provider: LLMProvider
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = 0.7
    max_tokens: int = 2048
    top_p: float = 1.0
    extra: Dict[str, Any] = Field(default_factory=dict)


# Alias for backward compatibility
LLMConfig = LLMProviderConfig


class LLMEngineConfig(BaseModel):
    """Top‑level engine configuration – injected once at start‑up."""
    default_provider: LLMProvider = LLMProvider.PLACEHOLDER
    providers: Dict[str, LLMProviderConfig] = Field(default_factory=dict)
    enable_conversation_history: bool = True
    max_history_len: int = 10