"""
Memory Engine type definitions.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field
import uuid


class MemoryScope(str, Enum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    SESSION = "session"


class MemoryType(str, Enum):
    CONVERSATION = "conversation"
    FACT = "fact"
    PREFERENCE = "preference"
    SKILL_RESULT = "skill_result"
    SESSION = "session"


# Type aliases for common memory types
MemoryRecordId = str
MemoryScopeType = MemoryScope
MemoryTypeType = MemoryType


class MemorySearchParams(BaseModel):
    query: str
    top_k: int = 5
    scope: Optional["MemoryScope"] = None
    type_: Optional[str] = None
    session_id: Optional[str] = None
    tags: Optional[List[str]] = None
    min_importance: float = 0.0
    min_score: float = 0.0


class MemoryFilterParams(BaseModel):
    scope: Optional[str] = None
    type_: Optional[str] = None
    session_id: Optional[str] = None
    tags: Optional[List[str]] = None
    min_importance: float = 0.0
    before: Optional[datetime] = None
    after: Optional[datetime] = None


class MemoryStats(BaseModel):
    total_memories: int
    short_term_count: int
    long_term_count: int
    session_count: int
    expired_count: int
    total_size_bytes: int


class MemoryHealth(BaseModel):
    status: str
    total_memories: int
    storage_backend: str
    expired_count: int
    last_cleanup: Optional[datetime] = None


class MemorySearchResult(BaseModel):
    memory: "MemoryRecord"
    score: float
    matched_fields: List[str] = Field(default_factory=list)