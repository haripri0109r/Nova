"""
OpenRouter LLM Provider - Access to multiple free/paid models via OpenRouter API.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import httpx

from .provider import BaseLLMProvider

log = logging.getLogger("nova.llm.openrouter")


class OpenRouterClient(BaseLLMProvider):
    """Synchronous OpenRouter client for use in sync contexts."""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://openrouter.ai/api/v1",
        timeout: float = 30.0,
    ) -> None:
        super().__init__("openrouter")
        self._model = model
        self._api_key = api_key or os.getenv("OPENROUTER_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None

    def initialize(self) -> bool:
        """Initialize and test OpenRouter connection (sync)."""
        if not self._api_key:
            log.warning("OpenRouter API key not configured")
            self._initialized = False
            return False

        try:
            self._client = httpx.Client(
                timeout=self._timeout,
                base_url=self._base_url,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": "https://github.com/nova-voice-assistant",
                    "X-Title": "Nova Voice Assistant",
                },
            )

            # Test with models endpoint
            response = self._client.get("/models")
            response.raise_for_status()

            self._initialized = True
            log.info("OpenRouter initialized with model: %s", self._model)
            return True

        except httpx.HTTPError as exc:
            log.warning("OpenRouter connection failed: %s", exc)
            self._initialized = False
            return False
        except Exception as exc:
            log.error("OpenRouter initialization failed: %s", exc)
            self._initialized = False
            return False

    def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """Generate intent from transcript using OpenRouter (sync)."""
        if not self._initialized or not self._client:
            raise RuntimeError("OpenRouter not initialized")

        messages = self._build_chat_messages(transcript)

        try:
            response = self._client.post(
                "/chat/completions",
                json={
                    "model": self._model,
                    "messages": messages,
                    "temperature": 0.1,
                    "max_tokens": 150,
                    "response_format": {"type": "json_object"},
                },
            )
            response.raise_for_status()
            data = response.json()

            content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
            log.debug("OpenRouter raw response: %s", content)

            parsed = json.loads(content)
            return self._validate_intent(parsed)

        except json.JSONDecodeError as exc:
            log.warning("OpenRouter returned invalid JSON: %s", exc)
            raise RuntimeError("Invalid JSON from OpenRouter") from exc
        except httpx.HTTPError as exc:
            log.error("OpenRouter API error: %s", exc)
            raise RuntimeError(f"OpenRouter API error: {exc}") from exc

    def health_check(self) -> bool:
        """Check if OpenRouter is healthy."""
        if not self._initialized or not self._client:
            return False
        try:
            response = self._client.get("/models", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False