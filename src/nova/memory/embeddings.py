"""
Embedding providers for generating vector embeddings.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional
import hashlib
import logging

logger = logging.getLogger(__name__)


class EmbeddingProvider(ABC):
    """Abstract base class for embedding providers."""

    @abstractmethod
    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a list of texts."""
        pass

    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text."""
        embeddings = await self.generate_embeddings([text])
        return embeddings[0] if embeddings else []


class DefaultEmbeddingProvider(EmbeddingProvider):
    """Default embedding provider using simple hash-based embeddings."""

    def __init__(self, dimensions: int = 384):
        self._dimensions = dimensions

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate simple hash-based embeddings."""
        import hashlib
        embeddings = []
        for text in texts:
            # Create a deterministic hash-based embedding
            hash_bytes = hashlib.md5(text.encode()).digest()
            # Convert to float vector
            vector = [b / 255.0 for b in hash_bytes]
            # Pad or truncate to desired dimensions
            if len(vector) < 384:
                vector.extend([0.0] * (384 - len(vector)))
            else:
                vector = vector[:384]
            embeddings.append(vector)
        return embeddings


class LLMEmbeddingProvider(EmbeddingProvider):
    """LLM-based embedding provider using LLMManager."""

    def __init__(self, llm_manager=None):
        self._llm_manager = llm_manager

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings using LLM manager."""
        if not self._llm_manager:
            logger.warning("No LLM manager available, falling back to default provider")
            return await DefaultEmbeddingProvider().generate_embeddings(texts)

        try:
            # Check if LLM manager has generate_embeddings method
            if hasattr(self._llm_manager, 'generate_embeddings'):
                return await self._llm_manager.generate_embeddings(texts)
            else:
                logger.warning("LLM manager does not have generate_embeddings method")
                return await DefaultEmbeddingProvider().generate_embeddings(texts)
        except Exception as e:
            logger.warning(f"LLM embedding failed: {e}, falling back to default")
            return await DefaultEmbeddingProvider().generate_embeddings(texts)


def get_embedding_provider(provider_type: str = "default", **kwargs) -> EmbeddingProvider:
    """Factory function to get embedding provider."""
    if provider_type == "llm":
        # Will be initialized later with LLM manager
        return LLMEmbeddingProvider()
    return DefaultEmbeddingProvider()