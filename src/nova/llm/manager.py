"""Provider registry + life‑cycle – completely hidden from the rest of Nova."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field

from .providers import BaseLLMProvider, PlaceholderProvider, create_provider, get_available_providers
from .config import LLMEngineConfig, LLMProviderConfig, LLMConfig
from .models import ExecutionRequest, ExecutionResponse
from .parser import get_parser
from .exceptions import LLMEngineError, LLMProviderError, LLMGenerationError, LLMValidationError, LLMParsingError, LLMConfigurationError
from .conversation import ConversationManager
from .context import ContextBuilder
from .prompt_builder import PromptBuilder
from .models import LLMRequest, LLMResponse, StructuredResponse, ExecutionResponse, ExecutionResult

_log = logging.getLogger("nova.llm.manager")


@dataclass
class LLMManagerConfig:
    default_provider: str = "placeholder"
    providers: Dict[str, Any] = field(default_factory=dict)


class _PlaceholderAdapter(BaseLLMProvider):
    """Adapter to make PlaceholderProvider conform to canonical generate() contract."""
    def __init__(self, inner: PlaceholderProvider) -> None:
        super().__init__("placeholder")
        self._inner = inner

    # ----- Lifecycle delegation -----
    async def initialize(self) -> bool:
        return await self._inner.initialize()

    async def cleanup(self) -> None:
        await self._inner.cleanup()

    async def close(self) -> None:
        await self._inner.close()

    async def health_check(self) -> bool:
        return await self._inner.health_check()

    # ----- BaseLLMProvider properties -----
    @property
    def name(self) -> str:
        return self._inner.name

    @property
    def is_available(self) -> bool:
        return getattr(self._inner, "is_ready", False)

    @property
    def is_ready(self) -> bool:
        return getattr(self._inner, "is_ready", False)

    # ----- BaseLLMProvider (providers.py) abstract method -----
    async def translate(self, req) -> "StructuredResponse":
        # Extract text from LLMRequest (last user message)
        text = ""
        if hasattr(req, "messages") and req.messages:
            for msg in reversed(req.messages):
                if msg.role == "user":
                    text = msg.content
                    break
        # Create a simple object with .text attribute for inner.translate
        class _Req:
            def __init__(self, txt):
                self.text = txt
        return await self._inner.translate(_Req(text))

    # ----- BaseLLMProvider (provider.py) abstract method -----
    async def generate_intent(self, transcript: str) -> Dict[str, Any]:
        # Delegate to translate via a minimal request
        from .models import LLMRequest, LLMMessage
        req = LLMRequest(messages=[LLMMessage(role="user", content=transcript)])
        structured = await self.translate(req)
        return {
            "intent": structured.actions[0].tool if structured.actions else "unknown",
            "action": structured.actions[0].parameters.get("action", "none") if structured.actions else "none",
        }

    # ----- Canonical generation method -----
    async def generate(self, request: "LLMRequest") -> "LLMResponse":
        # Delegate to translate and wrap result into LLMResponse with JSON content
        structured = await self.translate(request)
        import json
        # Serialize the structured response as JSON string for parser
        json_str = json.dumps({
            "requires_execution": structured.requires_execution,
            "response_text": structured.response_text,
            "actions": [{"tool": a.tool, "parameters": a.parameters} for a in structured.actions]
        })
        from .models import LLMResponse
        return LLMResponse(
            content=json_str,
            tool_calls=[{"tool": a.tool, "parameters": a.parameters} for a in structured.actions],
            finish_reason="stop",
            usage={},
            model=None,
            provider=self.name,
            latency_ms=0,
            metadata={},
        )


class LLMManager:
    """
    Main orchestrator for the LLM pipeline.
    """

    def __init__(
        self,
        config: Optional[LLMManagerConfig] = None,
        store: Optional[Any] = None,
        embedding_provider: Optional[Any] = None,
        llm_config: Optional[LLMConfig] = None,
    ) -> None:
        self.config = config or LLMManagerConfig()
        self._config = llm_config or LLMConfig()
        self._providers: Dict[str, BaseLLMProvider] = {}
        self._current_provider: Optional[str] = None
        self._initialized = False

        # Components
        self._conversation_manager: Optional[ConversationManager] = None
        self._context_builder: Optional["ContextBuilder"] = None
        self._prompt_builder: Optional[PromptBuilder] = None
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

            # Initialize conversation manager
            self._conversation_manager = ConversationManager()
            await self._conversation_manager.initialize()

            # Initialize context builder
            from .context import ContextBuilder
            self._context_builder = ContextBuilder(
                conversation_manager=self._conversation_manager,
                config=self._config,
            )
            await self._context_builder.initialize()

            # Initialize prompt builder
            self._prompt_builder = PromptBuilder()

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

        except Exception as exc:
            _log.error(f"LLM Manager initialization failed: {exc}")
            raise LLMEngineError(f"Initialization failed: {exc}") from exc

    async def _add_provider(self, name: str, config: dict) -> None:
        """Add a provider instance."""
        provider_type = config.get("provider", "placeholder")
        # Build LLMProviderConfig from dict
        provider_cfg = LLMProviderConfig(
            provider=config.get("provider", "placeholder"),
            model=config.get("model"),
            api_key=config.get("api_key"),
            base_url=config.get("base_url"),
            temperature=config.get("temperature", 0.7),
            max_tokens=config.get("max_tokens", 2048),
            top_p=config.get("top_p", 1.0),
            extra=config.get("extra", {}),
        )
        provider = create_provider(provider_cfg)
        if provider:
            await provider.initialize()
            # Wrap PlaceholderProvider with adapter to provide generate()
            if isinstance(provider, PlaceholderProvider):
                provider = _PlaceholderAdapter(provider)
            if provider:
                await provider.initialize()
                self._providers[name] = provider
                _log.info(f"Registered LLM provider: {name} ({provider_type})")

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
        Main entry point: process user text through the full LLM pipeline.
        """
        if not self._initialized:
            await self.initialize()

        if not text or not text.strip():
            return ExecutionResponse(
                requires_execution=False,
                response_text="",
                actions=[],
                provider="none",
                latency_ms=0,
            )

        # 1️⃣ Conversation history
        if self._config.enable_conversation_history:
            await self._conversation_manager.add_message(session_id, "user", text)

        # Extract extra_context from caller-provided context
        extra_context = ""
        if context and isinstance(context, dict):
            extra_context = context.get("extra_context", "") or ""

        # 2️⃣ Build context via ContextBuilder
        context_data = await self._context_builder.build_context(
            session_id=session_id,
            system_prompt=self._get_system_prompt(),
            extra_context=extra_context,
            tools=self._get_tool_definitions(),
        )

        # 3️⃣ Build prompt via PromptBuilder
        messages = self._prompt_builder.build(context_data, user_input=text)

        # 4️⃣ Build LLMRequest
        request = LLMRequest(
            messages=[{"role": m.role, "content": m.content} for m in messages],
            task_type="conversation",
            temperature=self._config.default_temperature,
            max_tokens=self._config.default_max_tokens,
            top_p=self._config.default_top_p,
        )

        # 5️⃣ Select provider
        provider = self._select_provider()
        if not provider:
            raise LLMProviderError("No available LLM provider", provider="none")

        # 6️⃣ Generate response
        try:
            llm_response = await provider.generate(request)
        except Exception as exc:
            _log.error("Provider generation failed", exc_info=exc)
            raise LLMGenerationError("Provider generation failed") from exc

        # 7️⃣ Parse response
        try:
            structured = self._parser.parse(llm_response.content)
        except Exception as exc:
            _log.error("Failed to parse provider response", exc_info=exc)
            raise LLMParsingError("Failed to parse provider response") from exc

        # 8️⃣ Store assistant response
        if self._config.enable_conversation_history:
            await self._conversation_manager.add_message(
                session_id, "assistant", structured.response_text
            )

        return ExecutionResponse(
            requires_execution=structured.requires_execution,
            response_text=structured.response_text,
            actions=structured.actions,
            provider=self._current_provider or "unknown",
            latency_ms=0,
        )

    def _get_system_prompt(self) -> str:
        """Get system prompt for the LLM."""
        from .prompt_builder import SYSTEM_PROMPT
        return SYSTEM_PROMPT

    def _get_tool_definitions(self) -> List[Dict]:
        """Get available tool definitions."""
        from .prompt_builder import TOOL_DEFINITIONS
        return TOOL_DEFINITIONS

    def _select_provider(self) -> Optional[BaseLLMProvider]:
        """Select best available provider."""
        if not self._providers:
            # Create a default placeholder adapter with minimal config
            from .config import LLMProviderConfig
            fallback_cfg = LLMProviderConfig(provider="placeholder")
            return _PlaceholderAdapter(PlaceholderProvider(fallback_cfg))

        for name, provider in self._providers.items():
            if getattr(provider, "is_ready", False):
                self._current_provider = name
                return provider

        # Fallback
        from .config import LLMProviderConfig
        fallback_cfg = LLMProviderConfig(provider="placeholder")
        return _PlaceholderAdapter(PlaceholderProvider(fallback_cfg))

    async def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """
        Generate an intent dict from a user transcript using the best available provider.
        Expected return keys: intent, action, (optional) target, level, confidence.
        """
        provider = self._select_provider()
        if provider is None:
            # Fallback minimal intent
            return {"intent": "fallback", "action": "none", "confidence": 0.0}
        try:
            return await provider.generate_intent(transcript)
        except Exception as exc:
            _log.error(f"generate_intent failed: {exc}")
            return {"intent": "fallback", "action": "none", "confidence": 0.0}

    def get_available_providers(self) -> List[str]:
        return list(self._providers.keys())

    def get_current_provider(self) -> Optional[str]:
        return self._current_provider

    async def health_check(self) -> dict:
        health = {}
        for name, provider in self._providers.items():
            try:
                health[name] = {
                    "initialized": getattr(provider, "is_ready", False),
                    "name": provider.name,
                }
            except Exception as e:
                health[name] = {"error": str(e)}
        return health


# Global instance
_manager: Optional[LLMManager] = None


def get_llm_manager(config: Optional[LLMManagerConfig] = None) -> LLMManager:
    """Get or create global LLM Manager instance."""
    global _manager
    if _manager is None:
        _manager = LLMManager(config)
    return _manager


__all__ = ["LLMManager", "get_llm_manager", "LLMManagerConfig"]