"""Nova Memory Engine public API."""
from .engine import MemoryEngine, get_memory_engine
from .models import (
    MemoryRecord,
    MemorySearchResult,
    MemorySearchParams,
)
from .storage import MemoryStore, InMemoryStore
from .embeddings import EmbeddingProvider, DefaultEmbeddingProvider
from .types import MemoryScope, MemoryType
from .exceptions import (
    MemoryEngineError,
    MemoryConfigurationError,
    MemoryValidationError,
    MemoryStorageError,
    MemoryRetrievalError,
    MemoryEmbeddingError,
    MemoryProcessorError,
    MemoryTimeoutError,
    MemoryExpiredError,
    MemoryNotFoundError,
    MemoryLimitExceededError,
)

__all__ = [
    "MemoryEngine",
    "get_memory_engine",
    "MemoryRecord",
    "MemorySearchResult",
    "MemorySearchParams",
    "MemoryStore",
    "InMemoryStore",
    "EmbeddingProvider",
    "DefaultEmbeddingProvider",
    "MemoryScope",
    "MemoryType",
    "MemoryEngineError",
    "MemoryConfigurationError",
    "MemoryValidationError",
    "MemoryStorageError",
    "MemoryRetrievalError",
    "MemoryEmbeddingError",
    "MemoryProcessorError",
    "MemoryTimeoutError",
    "MemoryExpiredError",
    "MemoryNotFoundError",
    "MemoryLimitExceededError",
]