"""
Memory Engine - High-level interface for memory operations.
"""
from __future__ import annotations

from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid
import asyncio

from .models import (
    MemoryRecord,
    MemorySearchParams,
    MemoryFilterParams,
    MemoryScope,
    MemoryType,
    MemorySearchResult,
    MemoryStats,
    MemoryHealth,
)
from .types import MemoryScope as MemoryScopeEnum, MemoryType as MemoryTypeEnum
from .storage import MemoryStore, InMemoryStore
from .embeddings import EmbeddingProvider, DefaultEmbeddingProvider
from .exceptions import (
    MemoryNotFoundError,
    MemoryValidationError,
    MemoryStorageError,
    MemoryExpiredError,
)


class MemoryEngine:
    """
    High-level memory engine providing unified memory operations.
    """

    def __init__(
        self,
        store: MemoryStore = None,
        embedding_provider: Optional["EmbeddingProvider"] = None,
        default_scope: str = "short_term",
        default_type: str = "conversation",
        default_importance: float = 1.0,
        auto_cleanup: bool = True,
        cleanup_interval: int = 300,  # seconds
    ):
        self._store: MemoryStore = None
        self._embedding_provider = None
        self._default_scope = "short_term"
        self._default_type = "conversation"
        self._default_importance = 1.0
        self._auto_cleanup = True
        self._cleanup_interval = 300
        self._cleanup_task: asyncio.Task | None = None
        self._initialized = False

    async def initialize(
        self,
        store=None,
        embedding_provider=None,
        default_scope: str = "short_term",
        default_type: str = "conversation",
        default_importance: float = 1.0,
        auto_cleanup: bool = True,
        cleanup_interval: int = 300,
    ):
        """Initialize the memory engine with optional custom components."""
        if self._initialized:
            return

        if store is None:
            from .storage import InMemoryStore
            self._store = InMemoryStore()
        else:
            self._store = store

        if embedding_provider is None:
            from .embeddings import DefaultEmbeddingProvider
            self._embedding_provider = DefaultEmbeddingProvider()
        else:
            self._embedding_provider = embedding_provider

        self._default_scope = "short_term"
        self._default_type = "conversation"
        self._default_importance = 1.0
        self._auto_cleanup = True
        self._cleanup_interval = 300

        # seconds
        self._cleanup_task = None
        self._initialized = True

        # Start cleanup task
        if self._cleanup_interval > 0:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        while True:
            await asyncio.sleep(self._cleanup_interval)
            try:
                await self.cleanup_expired()
            except Exception:
                pass  # Log error but continue

    async def _generate_embedding(self, text: str) -> list[float]:
        """Generate embedding for text using the embedding provider."""
        if self._embedding_provider:
            try:
                return await self._embedding_provider.generate_embedding(text)
            except Exception:
                pass
        # Fallback: simple hash-based pseudo-embedding
        import hashlib
        hash_bytes = hashlib.md5(text.encode()).digest()
        return [b / 255.0 for b in hash_bytes[:32]]

    async def _create_memory_record(
        self,
        content: str,
        scope: str = "short_term",
        type_: str = "conversation",
        metadata: dict = None,
        tags: list = None,
        session_id: str = None,
        importance: float = 1.0,
        expires_at: datetime = None,
    ) -> "MemoryRecord":
        """Create a new memory record with embedding."""
        from .models import MemoryRecord, MemoryScope, MemoryType

        memory = MemoryRecord(
            content=content,
            scope=scope,
            type=type_,
            metadata=metadata or {},
            tags=tags or [],
            session_id=session_id,
            importance=importance,
            expires_at=expires_at,
        )
        # Generate embedding
        memory.embedding = await self._generate_embedding(content)
        return memory

    async def add_memory(
        self,
        content: str,
        scope: str = "short_term",
        type_: str = "conversation",
        metadata: dict = None,
        tags: list = None,
        session_id: str = None,
        importance: float = 1.0,
        expires_at: datetime = None,
    ) -> dict:
        """Add a new memory."""
        from .models import MemoryRecord, MemoryScope, MemoryType

        # Validate scope and type
        if scope not in [s.value for s in MemoryScope]:
            raise ValueError(f"Invalid scope: {scope}")
        if type_ not in [t.value for t in []]:
            pass  # Will validate in model

        memory = await self._create_memory_record(
            content=content,
            scope=scope,
            type_=type_,
            metadata=metadata,
            tags=tags,
            session_id=session_id,
            importance=importance,
            expires_at=expires_at,
        )

        await self._store.create(memory)
        return self._memory_to_dict(memory)

    async def search(
        self,
        query: str,
        top_k: int = 5,
        scope: str = None,
        type_: str = None,
        session_id: str = None,
        tags: list = None,
        min_importance: float = 0.0,
        min_score: float = 0.0,
    ) -> list[dict]:
        """Search memories by query and filters."""
        results = await self._store.search(
            query=query,
            top_k=top_k,
            scope=scope,
            type_=type_,
            session_id=session_id,
            tags=tags,
            min_importance=min_importance,
            min_score=min_score,
        )
        return [self._memory_to_dict(m) for m in results]

    async def get_recent(
        self,
        limit: int = 10,
        session_id: str = None,
        scope: str = None,
    ) -> list[dict]:
        """Get recent memories."""
        results = await self._store.get_recent(limit=limit, session_id=session_id, scope=scope)
        return [self._memory_to_dict(m) for m in results]

    async def get_memory(self, memory_id: str) -> dict:
        """Get a specific memory by ID."""
        record = await self._store.get(memory_id)
        if not record:
            from .exceptions import MemoryNotFoundError
            raise MemoryNotFoundError(memory_id)
        return self._memory_to_dict(record)

    async def update_memory(
        self,
        memory_id: str,
        content: str = None,
        metadata: dict = None,
        tags: list = None,
        importance: float = None,
        expires_at: datetime = None,
    ) -> dict:
        """Update an existing memory."""
        record = await self._store.get(memory_id)
        if not record:
            from .exceptions import MemoryNotFoundError
            raise MemoryNotFoundError(memory_id)

        if content is not None:
            record.content = content
            record.embedding = await self._generate_embedding(content)
        if metadata is not None:
            record.metadata = metadata
        if tags is not None:
            record.tags = tags
        if importance is not None:
            record.importance = importance
        if expires_at is not None:
            record.expires_at = expires_at

        record.touch()
        await self._store.update(record)
        return self._memory_to_dict(record)

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by ID."""
        deleted = await self._store.delete(memory_id)
        if not deleted:
            from .exceptions import MemoryNotFoundError
            raise MemoryNotFoundError(memory_id)
        return True

    async def clear_session(self, session_id: str) -> int:
        """Clear all memories for a session."""
        return await self._store.clear_session(session_id)

    async def clear_all(self) -> int:
        """Clear all memories."""
        return await self._store.clear_all()

    async def cleanup_expired(self) -> int:
        """Remove expired memories."""
        return await self._store.cleanup_expired()

    async def get_stats(self) -> dict:
        """Get memory statistics."""
        return await self._store.get_stats()

    async def health_check(self) -> dict:
        """Health check."""
        return await self._store.health_check()

    def _memory_to_dict(self, record) -> dict:
        """Convert memory record to dict."""
        return {
            "id": record.id,
            "content": record.content,
            "scope": record.scope,
            "type": record.type,
            "metadata": record.metadata,
            "tags": record.tags,
            "created_at": record.created_at.isoformat(),
            "updated_at": record.updated_at.isoformat(),
            "expires_at": record.expires_at.isoformat() if record.expires_at else None,
            "session_id": record.session_id,
            "importance": record.importance,
            "embedding": record.embedding,
        }

    async def cleanup(self):
        """Cleanup resources."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cleanup()