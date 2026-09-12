"""Memory Engine embedding providers."""
from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from typing import Any, List, Optional

from .config import MemoryConfig
from .exceptions import MemoryEmbeddingError


class EmbeddingProvider(ABC):
    """Abstract interface for embedding providers."""

    @abstractmethod
    async def initialize(self) -> None:
        """Initialize the provider (e.g., load models)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources."""

    @abstractmethod
    async def embed(self, text: str) -> List[float]:
        """Generate embedding for a single text."""

    @abstractmethod
    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts."""

    # Test compatibility methods
    async def generate_embedding(self, text: str) -> List[float]:
        """Generate embedding for a single text (alias for embed)."""
        return await self.embed(text)

    async def generate_embeddings(self, texts: List[str]) -> List[List[float]]:
        """Generate embeddings for a batch of texts (alias for embed_batch)."""
        return await self.embed_batch(texts)


class DefaultEmbeddingProvider(EmbeddingProvider):
    """Deterministic hash‑based embedding provider (no external dependencies)."""

    def __init__(self, dimensions: int = 384) -> None:
        self._dimensions = dimensions

    async def initialize(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        embeddings: List[List[float]] = []
        for text in texts:
            hash_bytes = hashlib.md5(text.encode()).digest()
            vector = [b / 255.0 for b in hash_bytes]
            if len(vector) < self._dimensions:
                vector.extend([0.0] * (self._dimensions - len(vector)))
            else:
                vector = vector[: self._dimensions]
            embeddings.append(vector)
        return embeddings


class SentenceTransformerEmbeddingProvider(EmbeddingProvider):
    """Sentence‑Transformer based embeddings (lazy‑loaded)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model = None

    async def initialize(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise MemoryEmbeddingError(
                "sentence-transformers package not installed"
            ) from exc
        self._model = SentenceTransformer(self._model_name)

    async def close(self) -> None:
        self._model = None

    async def embed(self, text: str) -> List[float]:
        return (await self.embed_batch([text]))[0]

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        if self._model is None:
            await self.initialize()
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return [emb.tolist() for emb in embeddings]


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Placeholder for OpenAI embeddings (not implemented)."""

    async def initialize(self) -> None:
        raise NotImplementedError("OpenAIEmbeddingProvider not implemented")

    async def close(self) -> None:
        pass

    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError("OpenAIEmbeddingProvider not implemented")

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("OpenAIEmbeddingProvider not implemented")


# Backward‑compatibility stubs (used by legacy __init__.py)
class LLMEmbeddingProvider(EmbeddingProvider):
    """Legacy LLM‑based provider – not implemented."""

    async def initialize(self) -> None:
        raise NotImplementedError("LLMEmbeddingProvider not implemented")

    async def close(self) -> None:
        pass

    async def embed(self, text: str) -> List[float]:
        raise NotImplementedError("LLMEmbeddingProvider not implemented")

    async def embed_batch(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError("LLMEmbeddingProvider not implemented")


def get_embedding_provider(*args: Any, **kwargs: Any) -> EmbeddingProvider:
    """Legacy factory – not implemented."""
    raise NotImplementedError("get_embedding_provider not implemented")


__all__ = [
    "EmbeddingProvider",
    "DefaultEmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "OpenAIEmbeddingProvider",
]