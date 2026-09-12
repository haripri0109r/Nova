"""LLM Engine abstract contracts – single source of truth for dependency injection."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

# Re-export the authoritative provider protocol to keep a single source of truth.
from .provider import LLMProvider  # noqa: F401

from .models import LLMMessage, StructuredResponse


class ConversationManager(ABC):
    """Contract for managing conversation history."""

    @abstractmethod
    async def add_message(self, session_id: str, role: str, content: str) -> None:
        """Append a message to the conversation."""

    @abstractmethod
    async def get_history(self, session_id: str, limit: int = 10) -> List[LLMMessage]:
        """Return the most recent messages for a session."""

    @abstractmethod
    async def clear(self, session_id: str) -> None:
        """Remove all messages for a session."""

    @abstractmethod
    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Return the full session data (metadata, timestamps, etc.)."""


class ContextBuilder(ABC):
    """Contract for building the prompt context sent to the LLM."""

    @abstractmethod
    async def build_context(
        self,
        session_id: str,
        user_text: str,
        system_prompt: str,
        available_tools: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        Construct the full prompt context passed to the LLM provider.

        Returns a dict that will be used by the provider to build the final request.
        """


class PromptBuilder(ABC):
    """Contract for constructing the final chat messages sent to the LLM."""

    @abstractmethod
    def build_prompt(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convert internal message representation into the provider‑specific
        chat‑completion format (e.g., OpenAI chat messages).
        """

    @abstractmethod
    def build_system_prompt(self, system_prompt: str, tools: Optional[List[Dict[str, Any]]] = None) -> str:
        """Create the full system prompt string including tool descriptions."""


__all__ = [
    "LLMProvider",
    "ConversationManager",
    "ContextBuilder",
    "PromptBuilder",
]