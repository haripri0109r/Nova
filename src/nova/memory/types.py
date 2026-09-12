"""Memory Engine enum definitions."""
from enum import Enum


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