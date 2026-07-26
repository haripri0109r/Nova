"""
Ollama LLM Provider - Local LLM inference via Ollama API.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

import httpx

from .provider import BaseLLMProvider

log = logging.getLogger("nova.llm.ollama")


class OllamaClient(BaseLLMProvider):
    """Ollama local LLM provider. Optional - never blocks Nova startup."""

    def __init__(
        self,
        model: str = "qwen3:8b",
        base_url: str = "http://localhost:11434",
    ) -> None:
        super().__init__("ollama")
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._client: Optional[httpx.Client] = None

    def initialize(self) -> bool:
        """Initialize Ollama client and check if model is available.
        
        Returns False silently if Ollama is not running - never blocks Nova.
        """
        try:
            self._client = httpx.Client(base_url=self._base_url, timeout=30.0)

            # Check if Ollama is running
            response = self._client.get("/api/tags")
            response.raise_for_status()

            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]

            if self._model not in model_names:
                log.debug("Ollama model '%s' not found. Available: %s", self._model, model_names)
                # Try to pull the model (optional, non-blocking)
                if not self._pull_model():
                    log.debug("Ollama model pull failed or skipped")
                    return False

            self._initialized = True
            log.info("Ollama initialized with model: %s", self._model)
            return True

        except httpx.HTTPError as exc:
            # Silent failure - Ollama is optional
            log.debug("Ollama not available: %s", exc)
            self._initialized = False
            return False
        except Exception as exc:
            log.debug("Ollama initialization failed: %s", exc)
            self._initialized = False
            return False

    def _pull_model(self) -> bool:
        """Attempt to pull the model from Ollama registry. Non-blocking."""
        try:
            log.debug("Pulling Ollama model: %s...", self._model)
            response = self._client.post(
                "/api/pull",
                json={"name": self._model},
                timeout=300.0,
            )
            response.raise_for_status()
            log.info("Ollama model pulled successfully")
            return True
        except httpx.HTTPError as exc:
            log.debug("Failed to pull Ollama model: %s", exc)
            return False

    def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """Generate intent from transcript using Ollama."""
        if not self._initialized or not self._client:
            raise RuntimeError("Ollama not initialized")

        prompt = self._build_prompt(transcript)

        try:
            response = self._client.post(
                "/api/generate",
                json={
                    "model": self._model,
                    "prompt": prompt,
                    "format": "json",
                    "options": {
                        "temperature": 0.1,
                        "num_predict": 150,
                    },
                    "stream": False,
                },
                timeout=60.0,
            )
            response.raise_for_status()

            data = response.json()
            raw = data.get("response", "").strip()
            log.debug("Ollama raw response: %s", raw)

            parsed = json.loads(raw)
            return self._validate_intent(parsed)

        except json.JSONDecodeError as exc:
            log.warning("Ollama returned invalid JSON: %s", exc)
            raise RuntimeError("Invalid JSON from Ollama") from exc
        except httpx.HTTPError as exc:
            log.error("Ollama API error: %s", exc)
            raise RuntimeError(f"Ollama API error: {exc}") from exc

    def health_check(self) -> bool:
        """Check if Ollama is healthy."""
        if not self._initialized or not self._client:
            return False
        try:
            response = self._client.get("/api/tags", timeout=5.0)
            return response.status_code == 200
        except Exception:
            return False

    def list_models(self) -> List[str]:
        """List available Ollama models."""
        if not self._client:
            return []
        try:
            response = self._client.get("/api/tags")
            response.raise_for_status()
            models = response.json().get("models", [])
            return [m.get("name", "") for m in models]
        except Exception:
            return []