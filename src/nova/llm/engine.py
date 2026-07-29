"""
LLM Engine - Main entry point.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from .models import (
    LLMRequest,
    LLMResponse,
    LLMResponseStructured,
    LLMAction,
    LLMMessage,
    ConversationContext,
    LLMActionResult,
    ExecutionRequest,
    ExecutionResult,
)
from .manager import LLMManager, get_llm_manager
from .parser import LLMParser
from .prompt_builder import PromptBuilder
from .providers import BaseLLMProvider, PlaceholderProvider, create_llm_provider
from .config import LLMConfig, LLMEngineConfig
from .exceptions import LLMEngineError, ProviderError as LLMProviderError, ParseError as LLMParseError
from .conversation import ConversationManager, get_conversation_manager
from .context import LLMContextManager

logger = logging.getLogger("nova.llm_engine.engine")


@dataclass
class LLMEngineConfig:
    """Configuration for the LLM Engine."""
    default_provider: str = "placeholder"
    providers: Dict[str, Any] = None
    default_temperature: float = 0.7
    default_max_tokens: int = 2048
    enable_conversation_history: bool = True
    max_history_length: int = 10


class LLMEngine:
    """
    High-level LLM Engine client.
    Provides simple interface for common operations.
    """

    def __init__(self, config: LLMEngineConfig = None):
        self.config = config or LLMEngineConfig()
        self._manager: Optional[LLMManager] = None
        self._parser: Optional[LLMParser] = None
        self._prompt_builder: Optional[PromptBuilder] = None
        self._conversation_manager: Optional[ConversationManager] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize all components."""
        if self._initialized:
            return True

        logger.info("Initializing LLM Engine...")

        try:
            # Initialize manager
            self._manager = get_llm_manager()
            await self._manager.initialize()

            # Initialize parser
            self._parser = LLMParser()

            # Initialize prompt builder
            self._prompt_builder = PromptBuilder()

            # Initialize conversation manager
            self._conversation_manager = get_conversation_manager()

            self._initialized = True
            logger.info("LLM Engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"LLM Engine initialization failed: {e}")
            raise

    async def cleanup(self) -> None:
        """Cleanup all resources."""
        if self._manager:
            await self._manager.cleanup()
        self._initialized = False

    # --- High-level methods ---

    async def chat(self, text: str, session_id: str = "default",
                   provider: str = None, stream: bool = False) -> str:
        """
        Simple chat interface.
        Returns the response text.
        """
        if not self._initialized:
            await self.initialize()

        # Get or create conversation
        context = self._conversation_manager.get_session(session_id)

        # Add user message
        user_msg = {"role": "user", "content": text}
        context.add_message(user_msg)

        # Build request
        request = self._build_request(context.messages)

        # Get response
        response = await self._get_response(request, provider)

        # Add assistant message
        assistant_msg = {"role": "assistant", "content": response.content}
        context.add_message(assistant_msg)

        return response.content

    async def execute_intent(self, text: str, session_id: str = "default") -> dict:
        """
        Process text and return structured execution request.
        This is the main entry point for the Brain Engine.
        """
        if not self._initialized:
            await self.initialize()

        # Build structured request
        request = self._build_structured_request(text)

        # Get structured response
        response = await self._get_structured_response(request)

        # Return as dict for Brain Engine
        return {
            "requires_execution": response.requires_execution,
            "response_text": response.response_text,
            "actions": [
                {
                    "tool": a.tool,
                    "parameters": a.parameters,
                    "description": a.description
                }
                for a in response.actions
            ]
        }

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> str:
        """Speech to text - placeholder for STT integration."""
        return "[STT not implemented]"

    async def synthesize(self, text: str, voice: str = None) -> bytes:
        """Text to speech - placeholder for TTS integration."""
        return b"[TTS not implemented]"

    def _build_request(self, messages: List[Dict]) -> dict:
        """Build LLM request from messages."""
        return {
            "messages": messages,
            "temperature": self.config.default_temperature,
            "max_tokens": self.config.default_max_tokens
        }

    def _build_structured_request(self, text: str) -> dict:
        """Build request for structured output."""
        return {
            "messages": [
                {"role": "system", "content": "SYSTEM_PROMPT"},
                {"role": "user", "content": text}
            ],
            "temperature": 0.3,  # Lower for structured output
            "max_tokens": 1024,
            "response_format": {"type": "json_object"}
        }

    async def _get_response(self, request: dict, provider: str = None) -> "LLMResponse":
        """Get response from LLM provider."""
        manager = self._manager
        return await manager.complete(request)

    async def _get_structured_response(self, request: dict) -> "LLMResponseStructured":
        """Get structured response from LLM."""
        # Get raw response
        raw_response = await self._get_response(request)

        # Parse and validate
        self._parser = self._parser or LLMParser()
        return self._parser.parse(raw_response.content)


# Global instance
_llm_engine: Optional[LLMEngine] = None


def get_llm_engine(config: LLMEngineConfig = None) -> LLMEngine:
    """Get or create global LLM Engine instance."""
    global _llm_engine
    if _llm_engine is None:
        _llm_engine = LLMEngine(config)
    return _llm_engine