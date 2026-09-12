"""LLM Engine configuration – single source of truth for all LLM settings."""
from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .types import LLMProvider


class LLMProviderConfig(BaseModel):
    """Per‑provider knobs – only the fields a provider actually needs."""
    provider: LLMProvider
    model: Optional[str] = None
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    extra: Dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseSettings):
    """Central configuration for the LLM Engine."""

    model_config = SettingsConfigDict(
        env_prefix="NOVA_LLM_",
        extra="ignore",
    )

    # Default provider to use when none is explicitly requested
    default_provider: LLMProvider = Field(default=LLMProvider.PLACEHOLDER)

    # Per‑provider configuration (key = provider name, value = provider config)
    providers: Dict[str, LLMProviderConfig] = Field(default_factory=dict)

    # Conversation history handling
    enable_conversation_history: bool = Field(default=True)
    max_history_len: int = Field(default=10, ge=1)

    # Default generation parameters (used when a provider does not override them)
    default_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    default_max_tokens: int = Field(default=2048, gt=0)
    default_top_p: float = Field(default=1.0, ge=0.0, le=1.0)

    # Optional default model name (used when a provider does not specify one)
    default_model: Optional[str] = None

    # Debug / diagnostics
    debug: bool = Field(default=False)


# Backward‑compatibility alias used by LLMManager
LLMEngineConfig = LLMConfig


__all__ = ["LLMConfig", "LLMEngineConfig", "LLMProviderConfig"]