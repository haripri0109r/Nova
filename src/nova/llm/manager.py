"""Provider registry + life‑cycle – completely hidden from the rest of Nova."""
from __future__ import annotations
import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from .providers import BaseLLMProvider, PlaceholderProvider, create_provider, get_available_providers
from .config import LLMEngineConfig
from .models import ExecutionRequest, ExecutionResponse
from .parser import get_parser
from .exceptions import LLMEngineError

_log = logging.getLogger("nova.llm.manager")


@dataclass
class LLMManagerConfig:
    default_provider: str = "placeholder"
    providers: Dict[str, Any] = field(default_factory=dict)


class LLMManager:
    """
    Provider registry + life‑cycle – completely hidden from the rest of Nova.
    """

    def __init__(self, config: Optional[LLMManagerConfig] = None):
        self.config = config or LLMManagerConfig()
        self._providers: Dict[str, BaseLLMProvider] = {}
        self._current_provider: Optional[str] = None
        self._initialized = False
        self._parser = None

    async def initialize(self, config: Optional[dict] = None) -> bool:
        """Initialize the LLM manager and all providers."""
        if self._initialized:
            return True

        _log.info("Initializing LLM Manager...")

        try:
            # Initialize parser
            from .parser import get_parser
            self._parser = get_parser()

            # Initialize providers based on config
            if self.config.providers:
                for name, provider_config in self.config.providers.items():
                    await self._add_provider(name, provider_config)
            else:
                # Default placeholder
                await self._add_provider("placeholder", {"provider": "placeholder"})

            self._initialized = True
            _log.info("LLM Manager initialized successfully")
            return True

        except Exception as e:
            _log.error(f"LLM Manager initialization failed: {e}")
            raise

    async def _add_provider(self, name: str, config: dict):
        """Add a provider instance."""
        provider_type = config.get("provider", "placeholder")
        provider_class = self._get_provider_class(provider_type)
        if provider_class:
            provider = provider_class(config)
            await provider.initialize()
            self._providers[name] = provider
            _log.info(f"Registered LLM provider: {name} ({provider_type})")

    def _get_provider_class(self, provider_type: str):
        """Get provider class from type."""
        from .providers import (
            PlaceholderProvider,
            _get_provider_class
        )
        from .types import LLMProvider

        try:
            provider_enum = LLMProvider(provider_type)
            return _get_provider_class(provider_enum)
        except ValueError:
            _log.warning(f"Unknown provider type: {provider_type}")
            return None

    async def cleanup(self) -> None:
        """Cleanup all providers."""
        for name, provider in self._providers.items():
            try:
                await provider.cleanup()
            except Exception as e:
                _log.warning(f"Error cleaning up provider {name}: {e}")
        self._providers.clear()
        self._initialized = False

    async def process(self, text: str, session_id: str = "default", 
                      task_type: str = "conversation",
                      context: Optional[dict] = None) -> ExecutionResponse:
        """
        Process text through the LLM pipeline.
        
        Flow:
        1. Build context (history, tools, system prompt)
        2. Build prompt
        3. Select provider
        4. Get LLM response
        5. Parse and validate response
        6. Store in conversation history
        7. Return structured response
        """
        if not self._initialized:
            await self.initialize()

        # Get or create conversation
        conv_manager = get_conversation_manager()
        session = conv_manager.get_session(session_id)

        # Add user message to history
        conv_manager.add_message(session_id, "user", text)

        # Build context
        context_builder = get_context_builder()
        context = context_builder.build_context(
            session_id=session_id,
            user_text=text,
            system_prompt=self._get_system_prompt(),
            available_tools=self._get_tool_definitions()
        )

        # Build LLM request
        from .models import LLMRequest, LLMMessage
        messages = [LLMMessage(role="user", content=text)]
        
        # Add conversation history
        history = conv_manager.get_history(session_id, limit=10)
        for msg in history:
            messages.insert(0, LLMMessage(role=msg["role"], content=msg["content"]))

        request = LLMRequest(
            messages=messages,
            task_type="conversation"
        )

        # Select provider
        provider = self._select_provider()

        # Get response from provider
        response = await provider.complete(request)

        # Parse response
        structured = self._parser.parse(response.content)

        # Store assistant response
        conv_manager.add_message(session_id, "assistant", structured.response_text)

        return ExecutionResponse(
            requires_execution=structured.requires_execution,
            response_text=structured.response_text,
            actions=structured.actions,
            provider=provider.name,
        )

    def _get_system_prompt(self) -> str:
        """Get system prompt for the LLM."""
        from .prompt_builder import SYSTEM_PROMPT
        return SYSTEM_PROMPT

    def _get_tool_definitions(self) -> List[Dict]:
        """Get available tool definitions."""
        from .prompt_builder import TOOL_DEFINITIONS
        return TOOL_DEFINITIONS

    def _select_provider(self):
        """Select best available provider."""
        if not self._providers:
            # Fallback to placeholder
            from .providers import PlaceholderProvider
            return PlaceholderProvider()

        # Return first available provider
        for name, provider in self._providers.items():
            if provider.is_initialized:
                self._current_provider = name
                return provider

        # Fallback
        from .providers import PlaceholderProvider
        return PlaceholderProvider()

    def get_available_providers(self) -> List[str]:
        """Get list of available providers."""
        return list(self._providers.keys())

    def get_current_provider(self) -> Optional[str]:
        return self._current_provider

    async def health_check(self) -> dict:
        """Check health of all providers."""
        health = {}
        for name, provider in self._providers.items():
            try:
                health[name] = {
                    "initialized": provider.is_initialized,
                    "name": provider.name
                }
            except Exception as e:
                health[name] = {"error": str(e)}
        return health


# Global instance
_manager = None


def get_llm_manager(config: LLMManagerConfig = None) -> LLMManager:
    """Get or create global LLM Manager instance."""
    global _manager
    if _manager is None:
        _manager = LLMManager(config)
    return _manager