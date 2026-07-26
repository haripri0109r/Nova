"""
Nova LLM Package - Provider-based LLM architecture.

Providers (in priority order):
1. Ollama - Local LLM inference
2. OpenRouter - Free cloud models
3. Gemini - Google Generative AI (fallback)
"""

from nova.llm.provider import BaseLLMProvider, LLMProvider
from nova.llm.gemini_client import GeminiClient
from nova.llm.ollama_client import OllamaClient
from nova.llm.openrouter_client import OpenRouterClient

__all__ = [
    "LLMProvider",
    "BaseLLMProvider",
    "GeminiClient",
    "OllamaClient",
    "OpenRouterClient",
]