"""
Memory storage abstraction layer.

Provides an abstract interface for memory storage backends and an in-memory implementation.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any, TYPE_CHECKING
from datetime import datetime
import asyncio
import uuid

if __name__ == "__main__":
    # For type checking
    from .models import MemoryRecord
else:
    from .models import MemoryRecord


class MemoryStore(ABC):
    """Abstract base class for memory storage backends."""

    @abstractmethod
    async def create(self, record) -> Any:
        """Create a new memory record."""
        pass

    @abstractmethod
    async def get(self, memory_id: str) -> Optional[object]:
        """Get a memory record by ID."""
        pass

    @abstractmethod
    async def update(self, record) -> Any:
        """Update an existing memory record."""
        pass

    @abstractmethod
    async def delete(self, memory_id: str) -> bool:
        """Delete a memory record by ID. Returns True if deleted."""
        pass

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 5,
        scope: Optional[str] = None,
        type_: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        min_score: float = 0.0,
    ) -> List[Any]:
        """Search memories by query and filters."""
        pass

    @abstractmethod
    async def get_recent(
        self,
        limit: int = 10,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List[Any]:
        """Get recent memories."""
        pass

    @abstractmethod
    async def filter(
        self,
        scope: Optional[str] = None,
        type_: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None,
    ) -> List[Any]:
        """Filter memories by criteria."""
        pass

    @abstractmethod
    async def clear_session(self, session_id: str) -> int:
        """Delete all memories for a session. Returns count deleted."""
        pass

    @abstractmethod
    async def clear_all(self) -> int:
        """Delete all memories. Returns count deleted."""
        pass

    @abstractmethod
    async def cleanup_expired(self) -> int:
        """Remove expired memories. Returns count deleted."""
        pass

    @abstractmethod
    async def get_stats(self) -> dict:
        """Get storage statistics."""
        pass

    @abstractmethod
    async def health_check(self) -> dict:
        """Health check for storage backend."""
        pass


class InMemoryStore:
    """Thread-safe in-memory memory store implementation."""

    def __init__(self):
        self._memories: dict[str, Any] = {}
        self._lock = asyncio.Lock()

    async def create(self, record) -> Any:
        async with self._lock:
            if not record.id:
                import uuid
                record.id = uuid.uuid4().hex
            record.created_at = datetime.utcnow()
            record.updated_at = datetime.utcnow()
            self._memories[record.id] = record
            return record

    async def get(self, memory_id: str):
        async with self._lock:
            return self._memories.get(memory_id)

    async def update(self, record) -> Any:
        async with self._lock:
            if record.id not in self._memories:
                raise KeyError(f"Memory {record.id} not found")
            record.updated_at = datetime.utcnow()
            self._memories[record.id] = record
            return record

    async def delete(self, memory_id: str) -> bool:
        async with self._lock:
            if memory_id in self._memories:
                del self._memories[memory_id]
                return True
            return False

    async def search(
        self,
        query: str,
        top_k: int = 5,
        scope: Optional[str] = None,
        type_: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        min_score: float = 0.0,
    ) -> List:
        # Simple text search on content (no embeddings)
        query_lower = query.lower()
        results = []
        async with self._lock:
            for record in self._memories.values():
                if record.is_expired():
                    continue
                if record.content.lower().find(query.lower()) == -1:
                    continue
                # Apply filters
                if scope and record.scope != scope:
                    continue
                if type_ and record.type != type_:
                    continue
                if session_id and record.session_id != session_id:
                    continue
                if tags and not any(tag in record.tags for tag in tags):
                    continue
                if record.importance < 0.0:
                    continue
                # Simple text match scoring
                content_lower = record.content.lower()
                score = content_lower.count(query_lower) / max(len(record.content.split()), 1)
                if score < 0.0:
                    continue
                results.append((record, score))
        # Sort by score desc, then importance, then recency
        results.sort(key=lambda x: (x[1], x[0].importance, x[0].created_at), reverse=True)
        return [r[0] for r in results[:top_k]]

    async def get_recent(
        self,
        limit: int = 10,
        session_id: Optional[str] = None,
        scope: Optional[str] = None,
    ) -> List:
        async with self._lock:
            results = []
            for record in self._memories.values():
                if record.is_expired():
                    continue
                if session_id and record.session_id != session_id:
                    continue
                if scope and record.scope != scope:
                    continue
                results.append(record)
            # Sort by updated_at desc
            results.sort(key=lambda r: r.updated_at, reverse=True)
            return results[:limit]

    async def filter(
        self,
        scope: Optional[str] = None,
        type_: Optional[str] = None,
        session_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
        min_importance: float = 0.0,
        before: Optional[datetime] = None,
        after: Optional[datetime] = None,
    ) -> List[Any]:
        async with self._lock:
            results = []
            for record in self._memories.values():
                if record.is_expired():
                    continue
                if scope and record.scope != scope:
                    continue
                if type_ and record.type != type_:
                    continue
                if session_id and record.session_id != session_id:
                    continue
                if tags and not any(tag in record.tags for tag in tags):
                    continue
                if record.importance < min_importance:
                    continue
                if before and record.created_at > before:
                    continue
                if after and record.created_at < after:
                    continue
                results.append(record)
            return results

    async def clear_session(self, session_id: str) -> int:
        async with self._lock:
            to_delete = [
                mid for mid, rec in self._memories.items()
                if rec.session_id == session_id
            ]
            for mid in to_delete:
                del self._memories[mid]
            return len(to_delete)

    async def clear_all(self) -> int:
        async with self._lock:
            count = len(self._memories)
            self._memories.clear()
            return count

    async def cleanup_expired(self) -> int:
        async with self._lock:
            expired = [
                mid for mid, rec in self._memories.items()
                if rec.is_expired()
            ]
            for mid in expired:
                del self._memories[mid]
            return len(expired)

    async def get_stats(self) -> dict:
        async with self._lock:
            total = len(self._memories)
            short_term = sum(1 for r in self._memories.values() if r.scope == "short_term")
            long_term = sum(1 for r in self._memories.values() if r.scope == "long_term")
            session_ids = set(r.session_id for r in self._memories.values() if r.session_id)
            expired = sum(1 for r in self._memories.values() if r.is_expired())
            total_size = sum(len(r.content.encode()) for r in self._memories.values())
            return {
                "total_memories": total,
                "short_term_count": short_term,
                "long_term_count": long_term,
                "session_count": len(session_ids),
                "expired_count": sum(1 for r in self._memories.values() if r.is_expired()),
                "total_size_bytes": sum(len(r.content.encode()) for r in self._memories.values()),
            }

    async def health_check(self) -> dict:
        stats = await self.get_stats()
        return {
            "status": "healthy",
            "storage_backend": "in_memory",
            "total_memories": len(self._memories),
            **stats,
        }