"""
Intent Engine – rule‑based + optional LLM backend with provider fallback.

Public API (unchanged):
    engine = IntentEngine(use_llm=True)   # or False (default)
    result = engine.parse("Turn on Bluetooth")
    # → {"intent":"settings.bluetooth","action":"enable"}
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Pattern

from nova.config import settings
from nova.llm.manager import get_llm_manager

_llm_manager = get_llm_manager()

log = logging.getLogger("nova.intent")


# ----------------------------------------------------------------------
# 1️⃣  Rule definitions – identical to the previous pure‑regex engine
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class _Rule:
    pattern: Pattern[str]
    intent: str
    action: str
    extract: Optional[Callable[[re.Match], Dict]] = None


_RULES: List[_Rule] = [
    # ---- Settings – Bluetooth ------------------------------------------------
    _Rule(
        pattern=re.compile(r"(?i)\b(turn|switch)\s+(on|enable)\s+bluetooth\b"),
        intent="settings.bluetooth",
        action="enable",
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(turn|switch)\s+(off|disable)\s+bluetooth\b"),
        intent="settings.bluetooth",
        action="disable",
    ),
    # ---- Settings – Wi‑Fi ----------------------------------------------------
    _Rule(
        pattern=re.compile(r"(?i)\b(turn|switch)\s+(on|enable)\s+wi[-\s]?fi\b"),
        intent="settings.wifi",
        action="enable",
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(turn|switch)\s+(off|disable)\s+wi[-\s]?fi\b"),
        intent="settings.wifi",
        action="disable",
    ),
    # ---- Generic "open <app>" ------------------------------------------------
    _Rule(
        pattern=re.compile(r"(?i)\bopen\s+([a-z0-9\.\+\- ]+)\b"),
        intent="app",
        action="open",
        extract=lambda m: {"target": m.group(1).strip()},
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(launch|start|run)\s+([a-z0-9\.\+\- ]+)\b"),
        intent="app",
        action="open",
        extract=lambda m: {"target": m.group(2).strip()},
    ),
    # ---- Volume --------------------------------------------------------------
    _Rule(
        pattern=re.compile(r"(?i)\b(set|change)\s+volume\s+(to\s+)?(\d{1,3})\b"),
        intent="audio.volume",
        action="set",
        extract=lambda m: {"level": int(m.group(3))},
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(increase|raise|up)\s+volume\b"),
        intent="audio.volume",
        action="increase",
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(decrease|lower|down)\s+volume\b"),
        intent="audio.volume",
        action="decrease",
    ),
    # ---- Brightness ----------------------------------------------------------
    _Rule(
        pattern=re.compile(r"(?i)\b(set|change)\s+brightness\s+(to\s+)?(\d{1,3})\b"),
        intent="display.brightness",
        action="set",
        extract=lambda m: {"level": int(m.group(3))},
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(increase|raise|up)\s+brightness\b"),
        intent="display.brightness",
        action="increase",
    ),
    _Rule(
        pattern=re.compile(r"(?i)\b(decrease|lower|down)\s+brightness\b"),
        intent="display.brightness",
        action="decrease",
    ),
    # ---- Power ---------------------------------------------------------------
    _Rule(
        pattern=re.compile(
            r"(?i)\b(shutdown|power\s+off|turn\s+off\s+(the\s+)?(pc|computer))\b"
        ),
        intent="power",
        action="shutdown",
    ),
    _Rule(pattern=re.compile(r"(?i)\b(restart|reboot)\b"), intent="power", action="restart"),
    _Rule(pattern=re.compile(r"(?i)\b(sleep|standby|suspend)\b"), intent="power", action="sleep"),
]


# ----------------------------------------------------------------------
# 3️⃣  Engine class
# ----------------------------------------------------------------------
class IntentEngine:
    """
    Stateless, thread‑safe intent classifier.

    Parameters
    ----------
    use_llm : bool
        If *True* the LLM provider chain is tried first (Ollama → OpenRouter → Gemini).
        On any failure the engine silently falls back to the rule‑based matcher.
    llm_client : Any | None
        Deprecated - kept for backward compatibility. Allows injection of a custom LLM.
    rules : list[_Rule] | None
        Custom rule list – mainly for unit‑tests.
    """

    def __init__(
        self,
        use_llm: bool = False,
        llm_client: Optional[Any] = None,
        rules: Optional[List[_Rule]] = None,
    ) -> None:
        self._rules = rules or _RULES
        self._use_llm = use_llm
        self._llm_client = llm_client  # backward compat

    # ------------------------------------------------------------------
    # Public API – **exactly the same signature as before**
    # ------------------------------------------------------------------
    def parse(self, transcript: str) -> Dict[str, Any]:
        """
        Convert *transcript* → structured intent dict.

        Returns a dict with at least ``intent`` and ``action``.
        On total failure returns ``{"intent":"unknown","action":"none"}``.
        """
        if not transcript:
            log.debug("Empty transcript → unknown")
            return {"intent": "unknown", "action": "none"}

        cleaned = transcript.strip()
        log.debug("Parsing transcript: %r", cleaned)

        # --------------------------------------------------------------
        # 1️⃣  Try LLM provider chain if requested
        # --------------------------------------------------------------
        if self._use_llm:
            # Use new provider chain
            llm_result = _llm_manager.generate_intent(cleaned)
            if llm_result:
                return llm_result

            # Backward compat: try injected client if provided
            if self._llm_client is not None:
                try:
                    llm_result = self._llm_client.complete(cleaned)
                    log.info("Legacy LLM produced intent: %s", llm_result)
                    return llm_result
                except Exception as exc:
                    log.warning("Legacy LLM backend failed, falling back to rules: %s", exc)

        # --------------------------------------------------------------
        # 2️⃣  Rule‑based fallback (unchanged logic)
        # --------------------------------------------------------------
        for rule in self._rules:
            m = rule.pattern.fullmatch(cleaned)
            if not m:
                continue

            result = {"intent": rule.intent, "action": rule.action}
            log.debug("Matched rule → intent=%s action=%s", rule.intent, rule.action)

            if rule.extract:
                try:
                    extra = rule.extract(m)
                    if extra:
                        result.update(extra)
                        log.debug("Extracted slots: %s", extra)
                except Exception as exc:                # pragma: no cover
                    log.warning("Slot extraction failed for rule %s: %s", rule.intent, exc)

            return result

        # --------------------------------------------------------------
        # 3️⃣  Nothing matched
        # --------------------------------------------------------------
        log.debug("No rule matched → unknown")
        return {"intent": "unknown", "action": "none"}


# ----------------------------------------------------------------------
# 4️⃣  Convenience singleton (mirrors other Nova modules)
# ----------------------------------------------------------------------
_engine: Optional[IntentEngine] = None


def get_intent_engine(
    use_llm: bool = False,
    llm_client: Optional[Any] = None,
) -> IntentEngine:
    """Process‑wide engine – creates on first call."""
    global _engine
    if _engine is None:
        _engine = IntentEngine(use_llm=use_llm, llm_client=llm_client)
    return _engine


# ----------------------------------------------------------------------
# 5️⃣  Simple manual test when the file is executed directly
# ----------------------------------------------------------------------
if __name__ == "__main__":                                 # pragma: no cover
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # ---- Rule‑only -------------------------------------------------------
    eng = IntentEngine(use_llm=False)
    for txt in [
        "Turn on Bluetooth",
        "Open VS Code",
        "Set volume to 70",
        "Make me a sandwich",
    ]:
        print(txt, "→", eng.parse(txt))

    # ---- With LLM chain (requires provider config) --------------------
    # eng_llm = IntentEngine(use_llm=True)
    # print(eng_llm.parse("Turn off Wi‑Fi"))