"""
Wake-word detection abstraction.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator, Callable
from dataclasses import dataclass

from .types import WakeWordEngine, WakeWordConfig, WakeWordState
from .models import WakeWordResult
from .exceptions import WakeWordError

logger = logging.getLogger("nova.voice.wake_word")


@dataclass
class WakeWordCapabilities:
    """Capabilities of a wake-word engine."""
    supports_multiple_keywords: bool = True
    supports_sensitivity: bool = True
    supports_streaming: bool = True
    supported_keywords: list = None

    def __post_init__(self):
        if self.supported_keywords is None:
            self.supported_keywords = ["hey nova", "hello nova", "ok nova"]


class BaseWakeWordProvider(ABC):
    """Abstract base class for wake-word detection providers."""

    def __init__(self, config: WakeWordConfig):
        self.config = config
        self._initialized = False
        self._listening = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the wake-word provider."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up provider resources."""
        pass

    @abstractmethod
    async def start_listening(self) -> None:
        """Start listening for wake word."""
        pass

    @abstractmethod
    async def stop_listening(self) -> None:
        """Stop listening for wake word."""
        pass

    @abstractmethod
    async def process_audio(self, audio_data: bytes) -> WakeWordResult:
        """Process audio chunk for wake word detection."""
        pass

    @abstractmethod
    async def listen_stream(self) -> AsyncIterator[WakeWordResult]:
        """Stream wake word detection results."""
        pass

    @property
    @abstractmethod
    def name(self) -> WakeWordEngine:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> WakeWordCapabilities:
        """Provider capabilities."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_listening(self) -> bool:
        return self._listening


class PlaceholderWakeWordProvider(BaseWakeWordProvider):
    """No-op wake-word provider for testing/offline mode."""

    def __init__(self, config: WakeWordConfig):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        logger.info("Placeholder wake-word provider initialized")
        return True

    async def cleanup(self) -> None:
        self._initialized = False
        self._listening = False

    async def start_listening(self) -> None:
        self._listening = True

    async def stop_listening(self) -> None:
        self._listening = False

    async def process_audio(self, audio_data: bytes) -> WakeWordResult:
        return WakeWordResult(
            detected=False,
            confidence=0.0,
            state=WakeWordState.DORMANT,
        )

    async def listen_stream(self) -> AsyncIterator[WakeWordResult]:
        """Yield placeholder results indefinitely."""
        while self._listening:
            yield WakeWordResult(
                detected=False,
                confidence=0.0,
                state=WakeWordState.DORMANT,
            )

    @property
    def name(self) -> WakeWordEngine:
        return WakeWordEngine.PLACEHOLDER

    @property
    def capabilities(self) -> WakeWordCapabilities:
        return WakeWordCapabilities()


class VoskWakeWordProvider(BaseWakeWordProvider):
    """Vosk-based wake-word detection."""

    def __init__(self, config: WakeWordConfig):
        super().__init__(config)
        self._model = None
        self._recognizer = None
        self._callback: Optional[Callable[[WakeWordResult], None]] = None

    async def initialize(self) -> bool:
        try:
            from vosk import Model, KaldiRecognizer
            import json

            if not self.config.model_path:
                raise WakeWordError("Vosk model path not configured")

            self._model = Model(self.config.model_path)
            self._recognizer = KaldiRecognizer(self._model, 16000)
            self._recognizer.SetWords(True)

            # Add keywords for wake word detection
            keywords = self.config.keywords
            if keywords:
                kw_list = [(kw, self.config.sensitivity) for kw in keywords]
                self._recognizer.SetKws(keywords, kw_list)

            self._initialized = True
            logger.info("Vosk wake-word provider initialized")
            return True

        except ImportError:
            logger.warning("vosk not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Vosk wake-word: {e}")
            return False

    async def cleanup(self) -> None:
        self._model = None
        self._recognizer = None
        self._initialized = False
        self._listening = False

    async def start_listening(self) -> None:
        if not self._initialized:
            raise WakeWordError("Provider not initialized")
        self._listening = True

    async def stop_listening(self) -> None:
        self._listening = False

    async def process_audio(self, audio_data: bytes) -> WakeWordResult:
        if not self._listening or not self._initialized:
            return WakeWordResult(
                detected=False,
                confidence=0.0,
                state=WakeWordState.DORMANT,
            )

        if self._recognizer.AcceptWaveform(audio_data):
            result = json.loads(self._recognizer.Result())
            text = result.get("text", "").lower()

            for keyword in self.config.keywords:
                if keyword.lower() in text:
                    return WakeWordResult(
                        detected=True,
                        keyword=keyword,
                        confidence=1.0,
                        state=WakeWordState.DETECTED,
                    )

        return WakeWordResult(
            detected=False,
            confidence=0.0,
            state=WakeWordState.ACTIVE,
        )

    async def listen_stream(self) -> AsyncIterator[WakeWordResult]:
        """This would be implemented with actual audio streaming."""
        self._listening = True
        while self._listening:
            # In real implementation, this would yield from audio stream
            yield WakeWordResult(
                detected=False,
                confidence=0.0,
                state=WakeWordState.ACTIVE,
            )

    @property
    def name(self) -> WakeWordEngine:
        return WakeWordEngine.VOSK

    @property
    def capabilities(self) -> WakeWordCapabilities:
        return WakeWordCapabilities(
            supports_multiple_keywords=True,
            supports_sensitivity=True,
            supported_keywords=["hey nova", "hello nova", "ok nova"],
        )


class PreciseWakeWordProvider(BaseWakeWordProvider):
    """Mycroft Precise-based wake-word detection."""

    def __init__(self, config: WakeWordConfig):
        super().__init__(config)
        self._engine = None

    async def initialize(self) -> bool:
        try:
            from precise_runner import PreciseEngine, PreciseRunner

            if not self.config.model_path:
                raise WakeWordError("Precise model path not configured")

            self._engine = PreciseEngine(
                engine_path="precise-engine",
                model_path=self.config.model_path,
            )
            self._initialized = True
            logger.info("Precise wake-word provider initialized")
            return True

        except ImportError:
            logger.warning("precise-runner not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Precise: {e}")
            return False

    async def cleanup(self) -> None:
        self._engine = None
        self._initialized = False
        self._listening = False

    async def start_listening(self) -> None:
        self._listening = True

    async def stop_listening(self) -> None:
        self._listening = False

    async def process_audio(self, audio_data: bytes) -> WakeWordResult:
        if not self._listening or not self._initialized:
            return WakeWordResult(
                detected=False,
                confidence=0.0,
                state=WakeWordState.DORMANT,
            )

        # In real implementation, feed audio to precise engine
        return WakeWordResult(
            detected=False,
            confidence=0.0,
            state=WakeWordState.ACTIVE,
        )

    async def listen_stream(self) -> AsyncIterator[WakeWordResult]:
        self._listening = True
        while self._listening:
            yield WakeWordResult(
                detected=False,
                confidence=0.0,
                state=WakeWordState.ACTIVE,
            )

    @property
    def name(self) -> WakeWordEngine:
        return WakeWordEngine.PRECISE

    @property
    def capabilities(self) -> WakeWordCapabilities:
        return WakeWordCapabilities()


# Provider registry
_wakeword_providers: Dict[WakeWordEngine, type] = {
    WakeWordEngine.PLACEHOLDER: PlaceholderWakeWordProvider,
    WakeWordEngine.VOSK: VoskWakeWordProvider,
    WakeWordEngine.PRECISE: PreciseWakeWordProvider,
}


def register_wakeword_provider(engine_type: WakeWordEngine, provider_class: type) -> None:
    """Register a new wake-word provider implementation."""
    _wakeword_providers[engine_type] = provider_class


def create_wakeword_provider(config: WakeWordConfig) -> BaseWakeWordProvider:
    """Factory function to create wake-word provider instance."""
    provider_class = _wakeword_providers.get(config.engine)
    if not provider_class:
        raise WakeWordError(
            f"Unknown wake-word engine: {config.engine}",
            engine=config.engine.value,
        )
    return provider_class(config)


def get_available_wakeword_engines() -> List[WakeWordEngine]:
    return list(_wakeword_providers.keys())


# High-level WakeWordDetector interface
class WakeWordDetector:
    """High-level wake-word detection interface."""

    def __init__(self, engine: WakeWordEngine = WakeWordEngine.PLACEHOLDER, config: Optional[WakeWordConfig] = None):
        self._provider = create_wakeword_provider(config or WakeWordConfig(engine=engine))
        self._callbacks: List[Callable[[WakeWordResult], None]] = []

    async def initialize(self) -> bool:
        return await self._provider.initialize()

    async def cleanup(self) -> None:
        await self._provider.cleanup()

    async def start(self) -> None:
        await self._provider.start_listening()

    async def stop(self) -> None:
        await self._provider.stop_listening()

    async def process(self, audio_data: bytes) -> WakeWordResult:
        return await self._provider.process_audio(audio_data)

    def on_wake_word(self, callback: Callable[[WakeWordResult], None]) -> None:
        """Register callback for wake word detection."""
        self._callbacks.append(callback)

    @property
    def name(self) -> WakeWordEngine:
        return self._provider.name

    @property
    def is_initialized(self) -> bool:
        return self._provider.is_initialized

    @property
    def is_listening(self) -> bool:
        return self._provider.is_listening


# Global instance
_wake_word_detector: Optional[WakeWordDetector] = None


def get_wake_word_detector(
    engine: WakeWordEngine = WakeWordEngine.PLACEHOLDER,
    config: Optional[WakeWordConfig] = None,
) -> WakeWordDetector:
    """Get or create global wake-word detector instance."""
    global _wake_word_detector
    if _wake_word_detector is None:
        _wake_word_detector = WakeWordDetector(engine, config)
    return _wake_word_detector