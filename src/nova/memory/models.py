"""
Memory data models.
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
import uuid

from .types import MemoryScope, MemoryType


class MemoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    scope: str = "short_term"  # will be validated to MemoryScope
    type: str = "conversation"
    content: str
    embedding: list[float] = []
    metadata: Dict[str, Any] = {}
    tags: List[str] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime | None = None
    session_id: str | None = None
    importance: float = Field(default=1.0, ge=0.0, le=1.0)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at

    def is_short_term(self) -> bool:
        return self.scope == "short_term"

    def is_long_term(self) -> bool:
        return self.scope == "long_term"

    def touch(self):
        self.updated_at = datetime.utcnow()

    # Make subscriptable for test compatibility
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class MemorySearchResult:
    def __init__(self, memory: 'MemoryRecord', score: float, matched_fields: list[str] = None):
        self.memory = memory
        self.score = score
        self.matched_fields = matched_fields or []

    def to_dict(self):
        return {
            "memory": self.memory.model_dump(),
            "score": self.score,
            "matched_fields": self.matched_fields,
        }

    # Make subscriptable for test compatibility
    def __getitem__(self, key: str) -> Any:
        if key == "memory":
            return self.memory
        elif key == "score":
            return self.score
        elif key == "matched_fields":
            return self.matched_fields
        elif key == "content":
            return self.memory.content
        elif key == "scope":
            return self.memory.scope
        elif key == "type":
            return self.memory.type
        elif key == "id":
            return self.memory.id
        elif key == "metadata":
            return self.memory.metadata
        elif key == "tags":
            return self.memory.tags
        elif key == "session_id":
            return self.memory.session_id
        elif key == "importance":
            return self.memory.importance
        elif key == "embedding":
            return self.memory.embedding
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        try:
            self[key]
            return True
        except KeyError:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


class MemorySearchParams:
    def __init__(
        self,
        query: str,
        top_k: int = 5,
        scope: str | None = None,
        type_: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
        min_score: float = 0.0,
    ):
        self.query = query
        self.top_k = top_k
        self.scope = scope
        self.type = type_
        self.session_id = session_id
        self.tags = tags or []
        self.min_importance = min_importance
        self.min_score = min_score


class MemoryFilterParams:
    def __init__(
        self,
        scope: str | None = None,
        type_: str | None = None,
        session_id: str | None = None,
        tags: list[str] | None = None,
        min_importance: float = 0.0,
        before: datetime | None = None,
        after: datetime | None = None,
    ):
        self.scope = scope
        self.type = type_
        self.session_id = session_id
        self.tags = tags or []
        self.min_importance = min_importance
        self.before = before
        self.after = after


class MemoryStats:
    def __init__(
        self,
        total_memories: int,
        short_term_count: int,
        long_term_count: int,
        session_count: int,
        expired_count: int,
        total_size_bytes: int,
    ):
        self.total_memories = total_memories
        self.short_term_count = short_term_count
        self.long_term_count = long_term_count
        self.session_count = session_count
        self.expired_count = expired_count
        self.total_size_bytes = total_size_bytes

    def to_dict(self):
        return {
            "total_memories": self.total_memories,
            "short_term_count": self.short_term_count,
            "long_term_count": self.long_term_count,
            "session_count": self.session_count,
            "expired_count": self.expired_count,
            "total_size_bytes": self.total_size_bytes,
        }

    # Make subscriptable for test compatibility
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


class MemoryHealth:
    def __init__(
        self,
        status: str,
        total_memories: int,
        storage_backend: str,
        expired_count: int,
        last_cleanup: str | None = None,
    ):
        self.status = status
        self.total_memories = total_memories
        self.storage_backend = storage_backend
        self.expired_count = expired_count
        self.last_cleanup = last_cleanup

    def to_dict(self):
        return {
            "status": self.status,
            "total_memories": self.total_memories,
            "storage_backend": self.storage_backend,
            "expired_count": self.expired_count,
            "last_cleanup": self.last_cleanup,
        }

    # Make subscriptable for test compatibility
    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)

    def __contains__(self, key: str) -> bool:
        return hasattr(self, key)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __iter__(self):
        """Allow iteration over keys for 'in' operator."""
        return iter(self.to_dict().keys())