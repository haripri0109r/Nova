from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

from llama_cpp import Llama

from .loader import get_llm, ModelLoadError
from .prompts import SYSTEM_PROMPT, FEW_SHOT
from .schema import Intent, parse_intent, ValidationError

log = logging.getLogger("nova.intent.engine")

# ----------------------------------------------------------------------
# Helper – build the chat‑completion payload expected by llama‑cpp
# ----------------------------------------------------------------------
def _build_messages(user_text: str) -> List[Dict[str, str]]:
    msgs = [{"role": "system", "content": SYSTEM_PROMPT}]
    for ex in FEW_SHOT:
        msgs.append(ex)                       # few‑shot examples
    msgs.append({"role": "user", "content": user_text})
    return msgs


# ----------------------------------------------------------------------
# Public engine class – thin, testable, swappable
# ----------------------------------------------------------------------
class LocalIntentEngine:
    """
    *Only* responsibility: **utterance → validated Intent**.
    All failures are logged and turned into a low‑confidence Intent so the
    SkillRouter can decide to ask for clarification.
    """

    _MIN_CONFIDENCE = 0.75          # threshold defined in the spec

    def __init__(self, llm: Optional[Llama] = None) -> None:
        self._llm = llm or get_llm()

    # --------------------------------------------------------------
    # Public API – used by the rest of Nova (unchanged signature)
    # --------------------------------------------------------------
    def parse(self, utterance: str) -> Intent:
        """
        Convert *utterance* into a fully validated `Intent` object.
        Never raises – on any error returns a synthetic low‑confidence
        `Intent` (`confidence = 0.0`) which the router treats as
        “ask user for clarification”.
        """
        if not utterance or not utterance.strip():
            log.debug("Empty utterance → synthetic low‑confidence intent")
            return self._synthetic("empty_utterance")

        try:
            raw = self._call_model(utterance)
        except ModelLoadError:
            log.exception("Model unavailable – falling back to clarification")
            return self._synthetic("model_unavailable")
        except Exception:                      # pragma: no cover – defensive
            log.exception("Unexpected error during intent inference")
            return self._synthetic("inference_error")

        # ----------------------------------------------------------
        # Validate & coerce to the concrete Pydantic model
        # ----------------------------------------------------------
        try:
            intent = parse_intent(raw)
        except ValidationError as ve:
            log.warning("Model returned malformed JSON: %s – raw: %s", ve, raw)
            return self._synthetic("validation_error")

        # ----------------------------------------------------------
        # Confidence gate – keep the original confidence for logging
        # ----------------------------------------------------------
        if intent.confidence < self._MIN_CONFIDENCE:
            log.info(
                "Intent confidence %.2f < %.2f – will ask clarification",
                intent.confidence,
                self._MIN_CONFIDENCE,
            )
        return intent

    # --------------------------------------------------------------
    # Internal helpers
    # --------------------------------------------------------------
    def _call_model(self, text: str) -> Dict[str, Any]:
        """Send prompt to llama‑cpp and return *parsed* JSON dict."""
        messages = _build_messages(text)

        # llama‑cpp’s chat completion returns a dict with a `choices` list
        resp = self._llm.create_chat_completion(
            messages=messages,
            temperature=0.0,          # deterministic
            max_tokens=256,
            top_p=1.0,
            stop=["\n"],              # stop at first newline – model emits single‑line JSON
        )
        content = resp["choices"][0]["message"]["content"].strip()
        log.debug("Raw model output: %s", content)

        # Model may wrap JSON in code fences – strip them
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content, flags=re.IGNORECASE)

        return json.loads(content)

    @staticmethod
    def _synthetic(reason: str) -> Intent:
        """
        Produce a *fallback* Intent that the router will treat as
        “confidence too low → ask user”.  Uses a dummy intent name so the
        router can log the reason.
        """
        from .schema import IntentBase, Action
        return IntentBase(
            intent=f"fallback_{reason}",
            action=Action.SET,          # placeholder – never executed
            confidence=0.0,
        )


# ----------------------------------------------------------------------
# Backwards‑compatible factory used by existing Nova code
# ----------------------------------------------------------------------
_engine_instance: Optional[LocalIntentEngine] = None


def get_intent_engine() -> LocalIntentEngine:
    """Singleton accessor – mirrors the old `nova.intent.get_intent_engine`."""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = LocalIntentEngine()
    return _engine_instance