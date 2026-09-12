"""Memory Engine storage abstraction and default in‑memory implementation."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List, Optional

from .models import MemoryRecord
from .types import MemoryScope, MemoryType
from .exceptions import MemoryNotFoundError


class MemoryStore(ABC):
    """Abstract storage contract for memory back‑ends."""

    @abstractmethod
    async def initialize(self) -> None:
        """Prepare the backend (e.g., open connections)."""

    @abstractmethod
    async def close(self) -> None:
        """Release resources (e.g., close connections)."""

    @abstractmethod
    async def add(self, memory: MemoryRecord) -> MemoryRecord:
        """Persist a new memory record and return the stored record."""

    @abstractmethod
    async def get(self, memory_id: str) -> Optional[MemoryRecord]:
        """Retrieve a memory by its identifier."""

    @abstractmethod
    async def update(self, memory: MemoryRecord) -> MemoryRecord:
        """Update an existing memory record."""

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """Delete a memory by identifier. Returns True if deleted."""

    @abstractmethod
    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> List[MemoryRecord]:
        """List memories with optional pagination and filters.
        NOTE: Filtering is transitional; will move to RetrievalEngine/Processor.
        """

    @abstractmethod
    async def clear(self) -> int:
        """Remove all memories. Returns number of deleted records."""

    @abstractmethod
    async def count(
        self,
        *,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> int:
        """Return total number of memories matching optional filters.
        NOTE: Filtering is transitional; will move to RetrievalEngine/Processor.
        """

    @abstractmethod
    async def health_check(self) -> dict:
        """Return health status of the storage backend."""

    @abstractmethod
    async def get_stats(self) -> dict:
        """Return storage statistics."""

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove expired memories. Returns number of deleted records."""

    # Optional vector‑search stub – not implemented in the base in‑memory store.
    async def vector_search(self, *args: Any, **kwargs: Any) -> List[MemoryRecord]:
        """Vector similarity search (not implemented for the base in‑memory store)."""
        raise NotImplementedError("Vector search not supported by this storage backend.")


class InMemoryStore(MemoryStore):
    """Thread‑safe, async‑first in‑memory implementation of MemoryStore."""

    def __init__(self) -> None:
        self._memories: dict[str, MemoryRecord] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """No‑op for the in‑memory backend."""
        pass

    async def close(self) -> None:
        """No‑op for the in‑memory backend."""
        pass

    async def add(self, memory: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            if memory.id in self._memories:
                # treat as update if id already exists
                pass
            self._memories[memory.id] = memory
            return memory

    async def get(self, memory_id: str) -> Optional[MemoryRecord]:
        async with self._lock:
            return self._memories.get(memory_id)

    async def update(self, memory: MemoryRecord) -> MemoryRecord:
        async with self._lock:
            if memory.id not in self._memories:
                raise MemoryNotFoundError(memory.id)
            self._memories[memory.id] = memory
            return memory

    async def delete(self, memory_id: str) -> bool:
        async with self._lock:
            if memory_id in self._memories:
                del self._memories[memory_id]
                return True
            return False

    async def list(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> List[MemoryRecord]:
        async with self._lock:
            results = list(self._memories.values())
            # simple filtering (transitional)
            if scope:
                results = [m for m in results if m.scope == scope]
            if memory_type:
                results = [m for m in results if m.type == memory_type]
            if session_id:
                results = [m for m in results if m.session_id == session_id]
            # sort by created_at descending for recency
            results.sort(key=lambda m: m.created_at, reverse=True)
            return results[offset : offset + limit]

    async def clear(self) -> int:
        async with self._lock:
            count = len(self._memories)
            self._memories.clear()
            return count

    async def count(
        self,
        *,
        scope: Optional[MemoryScope] = None,
        memory_type: Optional[MemoryType] = None,
        session_id: Optional[str] = None,
    ) -> int:
        async with self._lock:
            cnt = 0
            for m in self._memories.values():
                if scope and m.scope != scope:
                    continue
                if memory_type and m.type != memory_type:
                    continue
                if session_id and m.session_id != session_id:
                    continue
                cnt += 1
            return cnt

    async def health_check(self) -> dict:
        total = len(self._memories)
        expired = sum(1 for m in self._memories.values() if m.expires_at and datetime.utcnow() > m.expires_at)
        return {
            "status": "healthy",
            "total_memories": total,
            "storage_backend": "in_memory",
            "expired_count": expired,
            "last_cleanup": None,
        }

    async def get_stats(self) -> dict:
        async with self._lock:
            total = len(self._memories)
            short_term = sum(1 for r in self._memories.values() if r.scope == MemoryScope.SHORT_TERM)
            long_term = sum(1 for r in self._memories.values() if r.scope == MemoryScope.LONG_TERM)
            session_ids = set(r.session_id for r in self._memories.values() if r.session_id)
            expired = sum(1 for r in self._memories.values() if r.expires_at and datetime.utcnow() > r.expires_at)
            total_size = sum(len(r.content.encode()) for r in self._memories.values())
            return {
                "total_memories": total,
                "short_term_count": short_term,
                "long_term_count": long_term,
                "session_count": len(session_ids),
                "expired_count": expired,
                "total_size_bytes": total_size,
            }

    async def cleanup_expired(self) -> int:
        async with self._lock:
            expired_ids = [
                mid for mid, rec in self._memories.items()
                if rec.expires_at and datetime.utcnow() > rec.expires_at
            ]
            for mid in expired_ids:
                del self._memories[mid]
            return len(expired_ids)

    # vector_search intentionally not implemented – raises NotImplementedError
    # inherited from MemoryStore


__all__ = ["MemoryStore", "InMemoryStore"]