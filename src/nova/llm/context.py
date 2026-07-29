"""
Context management for LLM Engine.
"""
from __future__ import annotations
from typing import Dict, Any, Optional, List
from datetime import datetime
from dataclasses import dataclass, field
from .models import LLMMessage


@dataclass
class LLMContext:
    """Context for LLM requests."""
    session_id: str = ""
    user_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


class LLMContextManager:
    """Manages context for LLM requests."""

    def __init__(self):
        self._contexts: Dict[str, LLMContext] = {}

    def get_context(self, session_id: str) -> LLMContext:
        """Get or create context for session."""
        if session_id not in self._contexts:
            self._contexts[session_id] = LLMContext(session_id=session_id)
        return self._contexts[session_id]

    def update_context(self, session_id: str, **kwargs) -> None:
        """Update context metadata."""
        ctx = self.get_context(session_id)
        ctx.metadata.update(kwargs)
        ctx.updated_at = datetime.utcnow()

    def clear_context(self, session_id: str) -> bool:
        """Clear context for session."""
        if session_id in self._contexts:
            del self._contexts[session_id]
            return True
        return False

    def clear_all(self) -> None:
        """Clear all contexts."""
        self._contexts.clear()


# Global instance
_context_manager = None


def get_context_manager() -> LLMContextManager:
    """Get global context manager."""
    global _context_manager
    if _context_manager is None:
        _context_manager = LLMContextManager()
    return _context_manager