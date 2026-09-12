"""Memory Engine – high‑level orchestration layer."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List, Optional, Dict, Any

from .config import MemoryConfig
from .models import MemoryRecord, MemorySearchResult, MemoryStats, MemoryHealth
from .types import MemoryScope, MemoryType
from .storage import MemoryStore, InMemoryStore
from .embeddings import EmbeddingProvider, DefaultEmbeddingProvider
from .processor import MemoryProcessor, ProcessedMemory
from .retrieval import RetrievalEngine
from .exceptions import (
    MemoryEngineError,
    MemoryNotFoundError,
    MemoryValidationError,
    MemoryStorageError,
    MemoryEmbeddingError,
    MemoryProcessorError,
)

logger = logging.getLogger(__name__)


class MemoryEngine:
    """High‑level orchestration layer for the Memory Engine."""

    def __init__(
        self,
        config: Optional[MemoryConfig] = None,
        store: Optional["MemoryStore"] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        processor: Optional["MemoryProcessor"] = None,
        retrieval: Optional["RetrievalEngine"] = None,
    ) -> None:
        self._config = config or MemoryConfig()
        self._store = store or InMemoryStore()
        self._embedding_provider = embedding_provider or DefaultEmbeddingProvider(dimensions=self._config.embedding_dimensions)
        self._processor = processor or MemoryProcessor()
        self._retrieval = retrieval or RetrievalEngine(self._store, self._embedding_provider, self._config)
        self._cleanup_task: Optional[asyncio.Task] = None
        self._initialized = False

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    async def initialize(
        self,
        store: Optional["MemoryStore"] = None,
        embedding_provider: Optional[EmbeddingProvider] = None,
        auto_cleanup: Optional[bool] = None,
        cleanup_interval: Optional[float] = None,
    ) -> None:
        if self._initialized:
            return
        
        # Allow overriding store and embedding_provider at initialize time
        if store is not None:
            self._store = store
        if embedding_provider is not None:
            self._embedding_provider = embedding_provider
            
        # Override config if provided
        if auto_cleanup is not None:
            self._config.enable_cleanup = auto_cleanup
        if cleanup_interval is not None:
            self._config.cleanup_interval_seconds = cleanup_interval
        
        # Handle mock objects in tests that don't have async initialize
        if hasattr(self._store, 'initialize') and asyncio.iscoroutinefunction(self._store.initialize):
            await self._store.initialize()
        elif hasattr(self._store, 'initialize'):
            # Sync initialize
            self._store.initialize()
            
        if hasattr(self._embedding_provider, 'initialize') and asyncio.iscoroutinefunction(self._embedding_provider.initialize):
            await self._embedding_provider.initialize()
        elif hasattr(self._embedding_provider, 'initialize'):
            # Sync initialize
            self._embedding_provider.initialize()
        
        self._initialized = True
        # start background cleanup if enabled
        if self._config.enable_cleanup and self._config.cleanup_interval_seconds > 0:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def cleanup(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Handle mock objects in tests
        if hasattr(self._store, 'close') and asyncio.iscoroutinefunction(self._store.close):
            await self._store.close()
        elif hasattr(self._store, 'close'):
            self._store.close()
            
        if hasattr(self._embedding_provider, 'close') and asyncio.iscoroutinefunction(self._embedding_provider.close):
            await self._embedding_provider.close()
        elif hasattr(self._embedding_provider, 'close'):
            self._embedding_provider.close()
            
        self._initialized = False

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(self._config.cleanup_interval_seconds)
            try:
                await self.cleanup_expired()
            except Exception:
                logger.exception("Cleanup loop error")

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    async def add_memory(
        self,
        content: str,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        type_: Optional[MemoryType] = None,  # alias for test compatibility
        metadata: Optional[dict] = None,
        tags: Optional[list[str]] = None,
        session_id: Optional[str] = None,
        importance: Optional[float] = None,
        expires_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Process, embed, and store a new memory."""
        if not self._initialized:
            await self.initialize()

        # Validate scope
        valid_scopes = [s.value for s in MemoryScope]
        effective_scope = scope or self._config.default_scope
        if effective_scope not in valid_scopes:
            raise ValueError(f"Invalid scope: {effective_scope}")

        # Use type_ if provided (test compatibility), otherwise memory_type
        effective_type = type_ or memory_type

        # 1️⃣  preprocess
        processed: ProcessedMemory = self._processor.process(content)

        # 2️⃣  generate embedding
        embedding: List[float] = []
        if self._config.enable_embeddings:
            try:
                embedding = await self._embedding_provider.embed(processed.content)
            except Exception as exc:
                raise MemoryEmbeddingError(f"Embedding generation failed: {exc}") from exc

        # 3️⃣  build record
        record = MemoryRecord(
            content=processed.content,
            scope=effective_scope,
            type=effective_type or processed.memory_type,
            embedding=embedding,
            metadata=metadata or {},
            tags=tags or processed.tags,
            session_id=session_id,
            importance=importance if importance is not None else processed.importance,
            expires_at=expires_at,
        )

        # 4️⃣  persist
        stored_record = await self._store.add(record)
        
        # Return as dict for test compatibility
        return stored_record.model_dump()

    async def search(
        self,
        query: str,
        top_k: int = 5,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        results = await self._retrieval.search(query, top_k, scope, memory_type, session_id)
        # Convert MemorySearchResult objects to dicts for test compatibility
        dicts = []
        for r in results:
            d = r.to_dict()
            # Flatten the memory fields for test compatibility
            d["content"] = r.memory.content
            d["scope"] = r.memory.scope
            d["type"] = r.memory.type
            d["id"] = r.memory.id
            d["metadata"] = r.memory.metadata
            d["tags"] = r.memory.tags
            d["session_id"] = r.memory.session_id
            d["importance"] = r.memory.importance
            d["embedding"] = r.memory.embedding
            d["created_at"] = r.memory.created_at
            d["updated_at"] = r.memory.updated_at
            dicts.append(d)
        return dicts

    async def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        records = await self._retrieval.get_recent(limit)
        return [r.model_dump() for r in records]

    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        if not self._initialized:
            await self.initialize()
        record = await self._store.get(memory_id)
        if record is None:
            raise MemoryNotFoundError(memory_id)
        return record.model_dump()

    async def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        importance: Optional[float] = None,
        **kwargs
    ) -> Dict[str, Any]:
        if not self._initialized:
            await self.initialize()
        record = await self._store.get(memory_id)
        if record is None:
            raise MemoryNotFoundError(memory_id)
        
        if content is not None:
            record.content = content
            record.touch()
        if importance is not None:
            record.importance = importance
        
        # Handle any other fields passed via kwargs
        for key, value in kwargs.items():
            if hasattr(record, key):
                setattr(record, key, value)
        
        updated_record = await self._store.update(record)
        return updated_record.model_dump()

    async def delete_memory(self, memory_id: str) -> bool:
        if not self._initialized:
            await self.initialize()
        result = await self._store.delete(memory_id)
        if not result:
            raise MemoryNotFoundError(memory_id)
        return True

    async def clear_session(self, session_id: str) -> int:
        if not self._initialized:
            await self.initialize()
        # Get all memories and delete those matching session_id
        memories = await self._store.list(limit=10000, session_id=session_id)
        count = 0
        for memory in memories:
            await self._store.delete(memory.id)
            count += 1
        return count

    async def clear_all(self) -> int:
        if not self._initialized:
            await self.initialize()
        return await self._store.clear()

    async def cleanup_expired(self) -> int:
        if not self._initialized:
            await self.initialize()
        return await self._store.cleanup_expired()

    # ------------------------------------------------------------------ #
    # Health & Stats
    # ------------------------------------------------------------------ #
    async def health_check(self) -> Dict[str, Any]:
        store_health = await self._store.health_check()
        health = MemoryHealth(
            status="healthy" if store_health.get("status") == "healthy" else "degraded",
            total_memories=store_health.get("total_memories", 0),
            storage_backend=store_health.get("storage_backend", "unknown"),
            expired_count=store_health.get("expired_count", 0),
            last_cleanup=store_health.get("last_cleanup"),
        )
        return health.to_dict()

    async def get_stats(self) -> Dict[str, Any]:
        stats = await self._store.get_stats()
        memory_stats = MemoryStats(
            total_memories=stats.get("total_memories", 0),
            short_term_count=stats.get("short_term_count", 0),
            long_term_count=stats.get("long_term_count", 0),
            session_count=stats.get("session_count", 0),
            expired_count=stats.get("expired_count", 0),
            total_size_bytes=stats.get("total_size_bytes", 0),
        )
        return memory_stats.to_dict()


# ------------------------------------------------------------------ #
# Singleton accessor
# ------------------------------------------------------------------ #
_memory_engine: Optional[MemoryEngine] = None


def get_memory_engine(
    config: Optional[MemoryConfig] = None,
    store: Optional["MemoryStore"] = None,
    embedding_provider: Optional[EmbeddingProvider] = None,
    processor: Optional["MemoryProcessor"] = None,
    retrieval: Optional["RetrievalEngine"] = None,
) -> MemoryEngine:
    global _memory_engine
    if _memory_engine is None:
        _memory_engine = MemoryEngine(
            config=config,
            store=store,
            embedding_provider=embedding_provider,
            processor=processor,
            retrieval=retrieval,
        )
    return _memory_engine


__all__ = ["MemoryEngine", "get_memory_engine"]