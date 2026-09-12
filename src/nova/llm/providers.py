"""Provider abstraction – every concrete class returns **exactly** StructuredResponse."""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import logging
from .models import StructuredResponse, ExecutionRequest
from .types import LLMProvider
from .config import LLMProviderConfig
from .exceptions import ProviderError

_log = logging.getLogger("nova.llm.providers")


class BaseLLMProvider(ABC):
    """All concrete providers implement this tiny surface."""
    def __init__(self, cfg: LLMProviderConfig):
        self.cfg = cfg
        self._ready = False

    @abstractmethod
    async def initialize(self) -> bool: ...

    @abstractmethod
    async def cleanup(self) -> None: ...

    @abstractmethod
    async def translate(self, req) -> "StructuredResponse":
        """Core operation – NL → StructuredResponse."""
        ...

    @property
    def name(self) -> str:
        return self.cfg.provider.value

    @property
    def is_ready(self) -> bool:
        return self._ready


# ----------------------------------------------------------------------
# Placeholder – used in tests / when no real provider is configured
# ----------------------------------------------------------------------
class PlaceholderProvider(BaseLLMProvider):
    async def initialize(self) -> bool:
        self._ready = True
        return True

    async def cleanup(self) -> None:
        self._ready = False

    async def translate(self, req) -> "StructuredResponse":
        # Very small keyword fallback – good enough for unit‑tests
        txt = req.text.lower()
        if any(k in txt for k in ("brightness", "dark")):
            return StructuredResponse(
                requires_execution=True,
                response_text="Sure! I set the brightness to 30 percent.",
                actions=[{"tool": "set_brightness", "parameters": {"value": 30}, "description": "lower brightness"}],
            )
        if any(k in txt for k in ("chrome", "browser")):
            return StructuredResponse(
                requires_execution=True,
                response_text="Opening Google Chrome.",
                actions=[{"tool": "open_application", "parameters": {"application": "chrome"}, "description": "open Chrome"}],
            )
        if any(k in txt for k in ("screen", "what's on", "what is on", "read my screen", "what's on my screen")):
            return StructuredResponse(
                requires_execution=True,
                response_text="Reading the screen for you.",
                actions=[{"tool": "screen.read", "parameters": {}, "description": "read screen"}],
            )
        return StructuredResponse(
            requires_execution=False,
            response_text="I'm ready. How can I help?",
            actions=[],
        )


# ----------------------------------------------------------------------
# Registry + factory (lazy import, so heavy deps are optional)
# ----------------------------------------------------------------------
_PROVIDER_REGISTRY: dict[str, type] = {
    "placeholder": PlaceholderProvider,
    "gemini": "nova.llm.gemini_client.GeminiClient",
    "openai": "nova.llm.openai_client.OpenAIClient",
    "claude": "nova.llm.claude_client.ClaudeClient",
    "ollama": "nova.llm.ollama_client.OllamaClient",
    "openrouter": "nova.llm.openrouter_client.OpenRouterClient",
}


def _import(path: str):
    mod, cls = path.rsplit(".", 1)
    module = __import__(mod, fromlist=[cls])
    return getattr(module, cls)


def _resolve(key: str):
    entry = _PROVIDER_REGISTRY.get(key)
    if not entry:
        return None
    if isinstance(entry, str):
        cls = _import(entry)
        _PROVIDER_REGISTRY[key] = cls
        return cls
    return entry


def register_provider(name: str, cls: type):
    _PROVIDER_REGISTRY[name] = cls


def create_provider(cfg: LLMProviderConfig):
    cls = _PROVIDER_REGISTRY.get(cfg.provider.value)
    if not cls:
        raise ProviderError(f"Unknown provider {cfg.provider}", provider=cfg.provider.value)
    if isinstance(cls, str):
        cls = __import__(cls.rsplit(".", 1)[0], fromlist=[cls.rsplit(".", 1)[1]])
        cls = getattr(cls, cls.rsplit(".", 1)[1])
        _PROVIDER_REGISTRY[cfg.provider.value] = cls
    return cls(cfg)


# Alias for compatibility
create_llm_provider = create_provider


def get_available_providers() -> list[str]:
    return list(_PROVIDER_REGISTRY.keys())