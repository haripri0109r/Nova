"""Conversation management for LLM Engine."""
from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import ConversationContext, LLMMessage
from .config import LLMConfig
from .exceptions import LLMConversationError


class ConversationManager:
    """Manages conversation history per session."""

    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self._config = config or LLMConfig()
        self._sessions: Dict[str, ConversationContext] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        """No‑op for now – kept for symmetry with other components."""
        return

    async def close(self) -> None:
        """Clear all sessions."""
        async with self._lock:
            self._sessions.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        *,
        name: Optional[str] = None,
        tool_calls: Optional[List[Dict[str, Any]]] = None,
        tool_call_id: Optional[str] = None,
    ) -> None:
        """Append a message to a session, respecting history length."""
        if not self._config.enable_conversation_history:
            return

        async with self._lock:
            session = self._get_or_create_session(session_id)
            msg = LLMMessage(
                role=role,
                content=content,
                name=name,
                tool_calls=tool_calls,
                tool_call_id=tool_call_id,
            )
            session.messages.append(msg)
            session.updated_at = datetime.utcnow()
            # enforce max history length
            max_len = self._config.max_history_len
            if len(session.messages) > max_len:
                # keep newest messages
                session.messages = session.messages[-max_len:]

    async def get_history(
        self,
        session_id: str,
        limit: Optional[int] = None,
    ) -> List[LLMMessage]:
        """Return recent messages for a session (newest last)."""
        async with self._lock:
            session = self._get_or_create_session(session_id)
            limit = limit or self._config.max_history_len
            return session.messages[-limit:]

    async def get_last_message(self, session_id: str) -> Optional[LLMMessage]:
        """Return the most recent message or None."""
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session or not session.messages:
                return None
            return session.messages[-1]

    async def clear(self, session_id: str) -> bool:
        """Remove a single session."""
        async with self._lock:
            if session_id in self._sessions:
                del self._sessions[session_id]
                return True
            return False

    async def clear_all(self) -> None:
        """Remove all sessions."""
        async with self._lock:
            self._sessions.clear()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _get_or_create_session(self, session_id: str) -> ConversationContext:
        if session_id not in self._sessions:
            self._sessions[session_id] = ConversationContext(session_id=session_id)
        return self._sessions[session_id]


# ----------------------------------------------------------------------
# Compatibility accessor (thin wrapper)
# ----------------------------------------------------------------------
_conversation_manager: Optional["ConversationManager"] = None
_manager_lock = asyncio.Lock()


async def get_conversation_manager(config: Optional["LLMConfig"] = None) -> "ConversationManager":
    """Return a process‑wide ConversationManager instance."""
    global _conversation_manager
    async with _manager_lock:
        if _conversation_manager is None:
            _conversation_manager = ConversationManager(config)
            await _conversation_manager.initialize()
        return _conversation_manager


__all__ = ["ConversationManager", "get_conversation_manager"]