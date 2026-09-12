"""Memory Engine configuration."""
from __future__ import annotations

from typing import Optional, List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .types import MemoryScope, MemoryType


class MemoryConfig(BaseSettings):
    """Central configuration for the Memory Engine."""

    model_config = SettingsConfigDict(
        env_prefix="NOVA_MEMORY_",
        extra="ignore",
    )

    # Default scope for new memories
    default_scope: MemoryScope = Field(default=MemoryScope.SHORT_TERM)

    # Default memory type for new memories
    default_memory_type: MemoryType = Field(default=MemoryType.CONVERSATION)

    # Cleanup interval in seconds
    cleanup_interval_seconds: int = Field(default=300, ge=1)

    # Dimensionality of embeddings
    embedding_dimensions: int = Field(default=384, ge=1)

    # Maximum number of memories to retain (0 = unlimited)
    max_memories: int = Field(default=0, ge=0)

    # Default top_k for search
    default_top_k: int = Field(default=5, ge=1)

    # Default importance for new memories
    default_importance: float = Field(default=1.0, ge=0.0, le=1.0)

    # Feature flags
    enable_embeddings: bool = Field(default=True)
    enable_cleanup: bool = Field(default=True)
    enable_processor: bool = Field(default=True)
    enable_retrieval: bool = Field(default=True)

    # Storage backend identifier (e.g., "in_memory", "postgres", "redis")
    storage_backend: str = Field(default="in_memory")

    # Embedding provider identifier (e.g., "default", "sentence_transformer", "openai")
    embedding_provider: str = Field(default="default")

    # Debug mode
    debug: bool = Field(default=False)


__all__ = ["MemoryConfig"]