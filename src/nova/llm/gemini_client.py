"""
Gemini Flash LLM client – isolated network / auth logic.
"""
from __future__ import annotations
import json
import logging
import os
from typing import Any, Dict, Protocol

log = logging.getLogger("nova.llm.gemini")

class LLMClient(Protocol):
    """Minimal surface required by IntentEngine."""
    def complete(self, prompt: str) -> Dict[str, Any]:
        """Send prompt, return validated JSON dict."""
        ...

class GeminiClient:
    """Concrete implementation using google.generativeai."""
    _MODEL_NAME = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    _SYSTEM_PROMPT = (
        "You are a strict NLU engine for a voice assistant called Nova.\n"
        "Given a user transcript, output ONLY a JSON object matching the schema:\n"
        "{\n"
        '  "intent": "string",\n'
        '  "action": "string",\n'
        '  "target": "string?",\n'
        '  "level": "integer?"\n'
        "}\n"
        "If unmappable, return {\"intent\":\"unknown\",\"action\":\"none\"}."
    )

    def __init__(self, api_key: str | None = None) -> None:
        # TODO: configure google.generativeai with api_key
        pass

    def complete(self, prompt: str) -> Dict[str, Any]:
        """Call the model, validate JSON, retry once on failure."""
        # TODO: build full prompt, call model, parse JSON, validate schema, retry once
        raise NotImplementedError