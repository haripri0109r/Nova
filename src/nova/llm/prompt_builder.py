"""Prompt building utilities for the LLM Engine."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from .models import LLMMessage
from .exceptions import LLMContextError


SYSTEM_PROMPT = "You are a helpful assistant."

TOOL_DEFINITIONS: List[Dict[str, Any]] = []


class PromptBuilder:
    """Deterministic prompt construction from a context dict and optional user input."""

    def __init__(self) -> None:
        # No configuration needed; purely deterministic.
        pass

    def build(
        self,
        context: Dict[str, Any],
        user_input: Optional[str] = None,
    ) -> List[LLMMessage]:
        """
        Build the ordered list of LLMMessage objects to be sent to the provider.

        The context dict is expected to contain the keys produced by ContextBuilder:
            - system_prompt: str
            - messages: List[dict]  # each dict has 'role' and 'content'
            - extra_context: str
            - tools: List[Dict] (optional)

        The returned list follows the deterministic order:
        1. System prompt (if provided) as a system message.
        2. Extra context (if any) as a system message.
        3. Conversation history messages (oldest -> newest) from context['messages'].
        4. Current user input (if provided) as a user message.
        """
        if not isinstance(context, dict):
            raise LLMContextError("Context must be a dict")

        messages: List[LLMMessage] = []

        # 1. System prompt
        system_prompt = context.get("system_prompt") or ""
        if system_prompt:
            messages.append(LLMMessage(role="system", content=system_prompt))

        # 2. Extra context
        extra_context = context.get("extra_context") or ""
        if extra_context:
            messages.append(LLMMessage(role="system", content=extra_context))

        # 3. Conversation history (already in correct order oldest->newest)
        for msg in context.get("messages", []):
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if content:
                messages.append(LLMMessage(role=role, content=content))

        # 4. Current user input (if provided and not already present as last message)
        if user_input is not None:
            # Avoid duplicate if the last message in history is the same user input
            if not (messages and messages[-1].role == "user" and messages[-1].content == user_input):
                messages.append(LLMMessage(role="user", content=user_input))

        return messages


__all__ = ["PromptBuilder", "SYSTEM_PROMPT", "TOOL_DEFINITIONS"]