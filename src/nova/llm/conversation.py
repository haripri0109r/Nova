"""Conversation management for LLM Engine."""
from __future__ import annotations
from typing import Dict, List, Optional
from datetime import datetime
from .models import ConversationContext, LLMMessage

class ConversationManager:
    """Manages conversation sessions and context."""

    def __init__(self, max_history: int = 10):
        self.sessions: Dict[str, ConversationContext] = {}
        self.max_history = max_history

    def get_session(self, session_id: str) -> ConversationContext:
        """Get or create a conversation session."""
        if session_id not in self.sessions:
            self.sessions[session_id] = ConversationContext(session_id=session_id)
        return self.sessions[session_id]

    def add_message(self, session_id: str, role: str, content: str, **kwargs) -> None:
        """Add a message to a session."""
        session = self.get_session(session_id)
        message = LLMMessage(role=role, content=content, **kwargs)
        session.add_message(message)

    def get_history(self, session_id: str, limit: int = None) -> List[dict]:
        """Get conversation history for a session."""
        session = self.get_session(session_id)
        limit = limit or self.max_history
        recent = session.get_recent(limit)
        return [{"role": m.role, "content": m.content} for m in recent]

    def clear_session(self, session_id: str) -> bool:
        """Clear a session."""
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False

    def get_messages_for_llm(self, session_id: str, include_system: bool = True, limit: int = None) -> List[dict]:
        """Get messages formatted for LLM API."""
        session = self.get_session(session_id)
        messages = []

        # Add system prompt if requested and present
        if include_system and session.messages:
            system_msgs = [m for m in session.messages if m.role == "system"]
            if system_msgs:
                messages.extend([{"role": m.role, "content": m.content} for m in system_msgs])

        # Add recent messages
        recent = session.get_recent(limit or self.max_history)
        messages.extend([{"role": m.role, "content": m.content} for m in recent])

        return messages

    def clear_all(self) -> None:
        """Clear all sessions."""
        self.sessions.clear()


# Global instance
_conversation_manager = None


def get_conversation_manager(max_history: int = 10) -> ConversationManager:
    """Get global conversation manager."""
    global _conversation_manager
    if _conversation_manager is None:
        _conversation_manager = ConversationManager(max_history=max_history)
    return _conversation_manager