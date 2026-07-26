"""
Gemini LLM Provider - Google Generative AI Flash model.

Refactored to use the BaseLLMProvider interface for the provider architecture.

TODO: Migrate to google-genai SDK (google-generativeai is deprecated).
See: https://github.com/google-gemini/deprecated-generative-ai-python
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

import google.generativeai as genai
from google.api_core.exceptions import GoogleAPICallError

from .provider import BaseLLMProvider
from ..config import settings

log = logging.getLogger("nova.llm.gemini")


class GeminiClient(BaseLLMProvider):
    """
    Thin wrapper around ``google.generativeai.GenerativeModel``.
    The model name can be overridden via config settings.
    """

    def __init__(self, api_key: Optional[str] = None) -> None:
        super().__init__("gemini")
        self._api_key = api_key or settings.llm_gemini_api_key
        self._model_name = settings.llm_gemini_model
        self._model = None

    def initialize(self) -> bool:
        """Initialize Gemini client."""
        if not self._api_key:
            log.warning("Gemini API key not configured")
            self._initialized = False
            return False

        try:
            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(self._model_name)
            self._initialized = True
            log.info("Gemini initialized with model: %s", self._model_name)
            return True
        except Exception as exc:
            log.error("Gemini initialization failed: %s", exc)
            self._initialized = False
            return False

    def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """Generate intent from transcript using Gemini."""
        if not self._initialized or not self._model:
            raise RuntimeError("Gemini not initialized")

        prompt = self._build_prompt(transcript)

        try:
            response = self._model.generate_content(prompt)
            raw = response.text.strip()
            log.debug("Gemini raw reply: %s", raw)

            data = json.loads(raw)
            return self._validate_intent(data)

        except json.JSONDecodeError as exc:
            log.warning("Gemini returned invalid JSON: %s", exc)
            raise RuntimeError("Invalid JSON from Gemini") from exc
        except GoogleAPICallError as exc:
            log.error("Gemini API call failed: %s", exc)
            raise RuntimeError(f"Gemini API error: {exc}") from exc

    def health_check(self) -> bool:
        """Check if Gemini is healthy."""
        if not self._initialized or not self._model:
            return False
        try:
            response = self._model.generate_content("test", generation_config={"max_output_tokens": 1})
            return bool(response.text)
        except Exception:
            return False