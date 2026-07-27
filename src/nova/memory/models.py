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