"""
LLM Provider Interface - Base protocol that all LLM providers must implement.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Protocol

log = logging.getLogger("nova.llm.provider")


# System prompt for intent extraction - single source of truth
SYSTEM_PROMPT = (
    "You are a strict NLU engine for a voice assistant called Nova.\n"
    "Given a user transcript, output ONLY a JSON object that matches "
    "the following schema (no extra keys, no comments, no markdown):\n\n"
    "{\n"
    '  "intent": "string",          // high-level domain, e.g. "settings.bluetooth"\n'
    '  "action": "string",          // what the user wants, e.g. "enable"\n'
    '  "target": "string?",         // optional - app name, device, etc.\n'
    '  "level": "integer?"          // optional - numeric value for volume/brightness\n'
    "}\n\n"
    "If the request cannot be mapped, return:\n"
    '{"intent":"unknown","action":"none"}'
)


class LLMProvider(Protocol):
    """Protocol that all LLM providers must implement."""

    def initialize(self) -> bool:
        """Initialize the provider. Returns True if successful."""
        ...

    def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """Generate intent from transcript. Returns dict with intent, action, target, level."""
        ...

    def health_check(self) -> bool:
        """Check if provider is healthy and available."""
        ...

    @property
    def name(self) -> str:
        """Provider name for logging."""
        ...

    @property
    def is_available(self) -> bool:
        """Whether provider is initialized and ready."""
        ...


class BaseLLMProvider(ABC):
    """Base abstract class for LLM providers with common functionality."""

    def __init__(self, name: str) -> None:
        self._name = name
        self._initialized = False

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_available(self) -> bool:
        return self._initialized

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the provider. Returns True if successful."""
        pass

    @abstractmethod
    def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """Generate intent from transcript."""
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check provider health."""
        pass

    def _validate_intent(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and normalize intent response."""
        if not isinstance(data, dict):
            raise ValueError("Response must be a dictionary")

        intent = data.get("intent", "unknown")
        action = data.get("action", "none")

        if not isinstance(intent, str):
            intent = str(intent)
        if not isinstance(action, str):
            action = str(action)

        result = {"intent": intent, "action": action}

        if "target" in data and data["target"]:
            result["target"] = str(data["target"])

        if "level" in data and data["level"] is not None:
            try:
                result["level"] = int(data["level"])
            except (ValueError, TypeError):
                pass

        return result

    def _build_prompt(self, transcript: str) -> str:
        """Build the system prompt for intent extraction (used for completion APIs)."""
        return f"{SYSTEM_PROMPT}\n\nUser: {transcript}\nJSON:"

    def _build_chat_messages(self, transcript: str) -> list[dict]:
        """Build chat messages for chat completion APIs (OpenRouter, etc.)."""
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ]