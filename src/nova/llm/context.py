"""Context building for LLM Engine."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from .config import LLMConfig
from .conversation import ConversationManager
from .exceptions import LLMContextError


class ContextBuilder:
    """Assembles the prompt context for LLM requests."""

    def __init__(
        self,
        conversation_manager: Optional["ConversationManager"] = None,
        config: Optional["LLMConfig"] = None,
    ) -> None:
        self._conversation_manager = conversation_manager
        self._config = config or LLMConfig()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the builder (no-op for now)."""
        self._initialized = True

    async def close(self) -> None:
        """Cleanup (no-op)."""
        self._initialized = False

    async def build_context(
        self,
        session_id: str,
        *,
        system_prompt: Optional[str] = None,
        extra_context: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """
        Assemble the prompt context for an LLM request.

        Returns a dict containing:
        - system_prompt: str
        - messages: List[Dict[str, str]] (chronological, newest last)
        - tools: Optional[List[Dict]]
        - extra_context: Optional[str]
        """
        if not self._initialized:
            raise LLMContextError("ContextBuilder not initialized")

        # Gather conversation history if enabled
        messages: List[Dict[str, str]] = []
        if self._config.enable_conversation_history and self._conversation_manager is not None:
            history = await self._conversation_manager.get_history(
                session_id, limit=self._config.max_history_len
            )
            # Convert LLMMessage to dicts preserving order (oldest first)
            for msg in history:
                messages.append({"role": msg.role, "content": msg.content})

        # System prompt
        system = system_prompt or ""

        # Extra context
        extra = extra_context or ""

        # Tools
        tool_defs = tools or []

        return {
            "system_prompt": system,
            "messages": messages,
            "tools": tool_defs,
            "extra_context": extra,
        }


# ----------------------------------------------------------------------
# Compatibility layer – thin wrappers for existing code expecting
# LLMContextManager / get_context_manager
# ----------------------------------------------------------------------
class LLMContextManager:
    """Thin wrapper around ContextBuilder to preserve existing API."""

    def __init__(
        self,
        conversation_manager: Optional["ConversationManager"] = None,
        config: Optional["LLMConfig"] = None,
    ) -> None:
        self._builder = ContextBuilder(conversation_manager=conversation_manager, config=config)

    async def initialize(self) -> None:
        await self._builder.initialize()

    async def close(self) -> None:
        await self._builder.close()

    async def build_context(
        self,
        session_id: str,
        *,
        system_prompt: Optional[str] = None,
        extra_context: Optional[str] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        return await self._builder.build_context(
            session_id,
            system_prompt=system_prompt,
            extra_context=extra_context,
            tools=tools,
        )


# ----------------------------------------------------------------------
# Compatibility accessor (thin wrapper)
# ----------------------------------------------------------------------
_context_builder: Optional["ContextBuilder"] = None
_builder_lock = asyncio.Lock()


async def get_context_builder(
    conversation_manager: Optional["ConversationManager"] = None,
    config: Optional["LLMConfig"] = None,
) -> "ContextBuilder":
    """Return a process-wide ContextBuilder instance."""
    global _context_builder
    async with _builder_lock:
        if _context_builder is None:
            _context_builder = ContextBuilder(
                conversation_manager=conversation_manager,
                config=config,
            )
            await _context_builder.initialize()
        return _context_builder


# Alias for backward compatibility
get_context_manager = get_context_builder


__all__ = ["ContextBuilder", "get_context_builder", "LLMContextManager", "get_context_manager"]