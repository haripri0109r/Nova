"""
Llama.cpp Provider - Local LLM provider using llama-cpp-python.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from llama_cpp import Llama

from ..config import settings
from .provider import BaseLLMProvider

log = logging.getLogger("nova.llm.llama_cpp")


class LlamaCppProvider(BaseLLMProvider):
    """
    Local LLM provider using llama-cpp-python.
    """

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

    def __init__(self) -> None:
        super().__init__("llama_cpp")
        self._model_path = settings.llm_llama_cpp_model
        self._ctx_size = settings.llm_llama_cpp_ctx
        self._n_threads = settings.llm_llama_cpp_threads
        self._n_gpu_layers = settings.llm_llama_cpp_gpu_layers
        self._temperature = settings.llm_llama_cpp_temp
        self._verbose = False
        self._llm = None

    def initialize(self) -> bool:
        """Initialize the llama-cpp model."""
        if self._initialized:
            return True

        model_path = Path(self._model_path).expanduser().resolve()
        if not model_path.is_file():
            log.error("Llama.cpp model not found at %s", model_path)
            return False

        log.info(
            "Loading llama.cpp model from %s (ctx=%d, threads=%d, gpu_layers=%d)",
            model_path,
            self._ctx_size,
            self._n_threads,
            self._n_gpu_layers,
        )

        try:
            self._llm = Llama(
                model_path=str(model_path),
                n_ctx=self._ctx_size,
                n_threads=self._n_threads,
                n_gpu_layers=self._n_gpu_layers,
                verbose=False,
                seed=42,
            )
            self._initialized = True
            log.info("Llama.cpp model loaded successfully")
            return True
        except Exception as exc:
            log.exception("Failed to load llama.cpp model: %s", exc)
            return False

    def generate_intent(self, transcript: str) -> Dict[str, Any]:
        """Generate intent using llama-cpp."""
        if not self._initialized:
            if not self.initialize():
                return {"intent": "unknown", "action": "none"}

        if not transcript:
            return {"intent": "unknown", "action": "none"}

        try:
            messages = [
                {"role": "system", "content": self.SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ]

            resp = self._llm.create_chat_completion(
                messages=messages,
                temperature=0.0,
                max_tokens=256,
                top_p=1.0,
                stop=["\n"],
            )

            content = resp["choices"][0]["message"]["content"].strip()
            log.debug("Raw model output: %s", content)

            # Strip code fences if present
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)

            result = json.loads(content)
            return self._validate_intent(result)

        except Exception as exc:
            log.exception("Llama.cpp generation failed: %s", exc)
            return {"intent": "unknown", "action": "none"}

    def health_check(self) -> bool:
        """Check if provider is healthy."""
        return self._initialized and self._llm is not None

    def _build_prompt(self, transcript: str) -> str:
        """Build the system prompt for intent extraction (used for completion APIs)."""
        return f"{self.SYSTEM_PROMPT}\n\nUser: {transcript}\nJSON:"

    def _build_chat_messages(self, transcript: str) -> list[dict]:
        """Build chat messages for chat completion APIs."""
        return [
            {"role": "system", "content": self.SYSTEM_PROMPT},
            {"role": "user", "content": transcript},
        ]