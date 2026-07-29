"""
Intent Classification abstraction and placeholder implementation.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .models import RecognizedInput, IntentResult
from .types import IntentCategory, ConfidenceLevel, IntentClassifierConfig
from .exceptions import IntentClassificationError


class BaseIntentClassifier(ABC):
    """Abstract base class for intent classifiers."""

    def __init__(self, config: Optional[IntentClassifierConfig] = None):
        self.config = config or IntentClassifierConfig()
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the classifier (load model, warm‑up, etc.)."""
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        """Release resources."""
        ...

    @abstractmethod
    async def classify(self, inp: RecognizedInput) -> IntentResult:
        """Classify the recognized text into an intent."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human readable name of the provider."""
        ...

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class PlaceholderIntentClassifier(BaseIntentClassifier):
    """No‑op classifier used for testing / offline mode."""

    def __init__(self, config: Optional[IntentClassifierConfig] = None):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def classify(self, inp: RecognizedInput) -> IntentResult:
        # Very naive keyword based fallback
        text = inp.text.lower()
        if any(k in text for k in ("open", "launch", "start")):
            cat = IntentCategory.OPEN_APPLICATION
            conf = 0.9
        elif any(k in text for k in ("close", "quit", "exit")):
            cat = IntentCategory.CLOSE_APPLICATION
            conf = 0.9
        elif any(k in text for k in ("search", "google", "lookup")):
            cat = IntentCategory.WEB_SEARCH
            conf = 0.8
        else:
            cat = IntentCategory.GENERAL_CONVERSATION
            conf = 0.5

        level = (
            ConfidenceLevel.HIGH if conf >= 0.8
            else ConfidenceLevel.MEDIUM if conf >= 0.5
            else ConfidenceLevel.LOW
        )
        return IntentResult(
            category=cat,
            confidence=conf,
            confidence_level=level,
            entities={},
            raw_scores={cat.value: conf},
        )

    @property
    def name(self) -> str:
        return "placeholder"


# Provider registry with lazy import support
_intent_providers: Dict[str, Any] = {
    "placeholder": PlaceholderIntentClassifier,
    # future providers can be added as "module.path.ClassName"
}


def _import_provider(class_path: str):
    module_path, class_name = class_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def _get_provider_class(key: str):
    entry = _intent_providers.get(key)
    if not entry:
        return None
    if isinstance(entry, str):
        cls = _import_provider(entry)
        _intent_providers[key] = cls
        return cls
    return entry


def register_intent_provider(name: str, provider_class: type) -> None:
    """Register a new intent classifier implementation."""
    _intent_providers[name] = provider_class


def create_intent_classifier(config: Optional[IntentClassifierConfig] = None) -> BaseIntentClassifier:
    """Factory to create an intent classifier instance."""
    cfg = config or IntentClassifierConfig()
    provider_cls = _get_provider_class(_intent_providers, cfg.provider)
    if not provider_cls:
        raise IntentClassificationError(f"Unknown intent classifier provider: {cfg.provider}")
    return provider_cls(config)


def get_available_intent_providers() -> List[str]:
    return list(_intent_providers.keys())