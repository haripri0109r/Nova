"""
Voice Provider abstraction and factory.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from .types import STTProvider, TTSProvider, WakeWordEngine, STTConfig, TTSConfig, WakeWordConfig, WakeWordState
from .models import SpeechResult, VoiceResponse, WakeWordResult
from .exceptions import ProviderError, STTError, TTSError, WakeWordError

logger = logging.getLogger("nova.voice.providers")


# Provider registries
_stt_providers: Dict[STTProvider, type] = {
    STTProvider.PLACEHOLDER: "src.nova.voice.providers.PlaceholderSTTProvider",
    STTProvider.VOSK: "src.nova.voice.stt.VoskSTTProvider",
    STTProvider.WHISPER: "src.nova.voice.stt.WhisperSTTProvider",
    STTProvider.FASTER_WHISPER: "src.nova.voice.stt.FasterWhisperSTTProvider",
    STTProvider.WHISPER_CPP: "src.nova.voice.stt.WhisperCppSTTProvider",
}

_tts_providers: Dict[TTSProvider, type] = {
    TTSProvider.PLACEHOLDER: "src.nova.voice.tts.PlaceholderTTSProvider",
    TTSProvider.PIPER: "src.nova.voice.tts.PiperTTSProvider",
    TTSProvider.ELEVENLABS: "src.nova.voice.tts.ElevenLabsTTSProvider",
    TTSProvider.WINDOWS_SAPI: "src.nova.voice.tts.WindowsSAPIProvider",
    TTSProvider.COQUI: "src.nova.voice.tts.CoquiTTSProvider",
}

_wakeword_providers: Dict[WakeWordEngine, type] = {
    WakeWordEngine.PLACEHOLDER: "src.nova.voice.wake_word.PlaceholderWakeWordProvider",
    WakeWordEngine.VOSK: "src.nova.voice.wake_word.VoskWakeWordProvider",
    WakeWordEngine.PRECISE: "src.nova.voice.wake_word.PreciseWakeWordProvider",
}


def _import_provider(class_path: str):
    """Import provider class from string path."""
    module_path, class_name = class_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def _get_provider_class(registry: Dict, key):
    """Get provider class, importing if necessary."""
    class_path = registry.get(key)
    if not class_path:
        return None
    if isinstance(class_path, str):
        # Lazy import
        cls = _import_provider(class_path)
        registry[key] = cls
        return cls
    return class_path


@dataclass
class ProviderCapabilities:
    """Capabilities of a voice provider."""
    supports_streaming: bool = False
    supports_vad: bool = False
    supported_languages: List[str] = None
    supported_voices: List[str] = None
    max_text_length: int = 5000
    sample_rates: List[int] = None

    def __post_init__(self):
        if self.supported_languages is None:
            self.supported_languages = ["en"]
        if self.supported_voices is None:
            self.supported_voices = ["default"]
        if self.sample_rates is None:
            self.sample_rates = [16000, 22050, 44100]


class BaseSTTProvider(ABC):
    """Abstract base class for Speech-to-Text providers."""

    def __init__(self, config: STTConfig):
        self.config = config
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the STT provider."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up provider resources."""
        pass

    @abstractmethod
    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> SpeechResult:
        """Transcribe audio to text."""
        pass

    @abstractmethod
    async def transcribe_stream(self, audio_stream) -> SpeechResult:
        """Transcribe streaming audio."""
        pass

    @property
    @abstractmethod
    def name(self) -> STTProvider:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Provider capabilities."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class BaseTTSProvider(ABC):
    """Abstract base class for Text-to-Speech providers."""

    def __init__(self, config: TTSConfig):
        self.config = config
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the TTS provider."""
        pass

    @abstractmethod
    async def cleanup(self) -> None:
        """Clean up provider resources."""
        pass

    @abstractmethod
    async def synthesize(self, request) -> VoiceResponse:
        """Synthesize speech from text."""
        pass

    @abstractmethod
    async def synthesize_stream(self, request) -> AsyncIterator[bytes]:
        """Stream synthesized audio."""
        pass

    @property
    @abstractmethod
    def name(self) -> TTSProvider:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Provider capabilities."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class BaseWakeWordProvider(ABC):
    """Abstract base class for Wake-Word detection providers."""

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

    @property
    @abstractmethod
    def name(self) -> WakeWordEngine:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Provider capabilities."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def is_listening(self) -> bool:
        return self._listening


# Placeholder implementations for testing/offline mode

class PlaceholderSTTProvider(BaseSTTProvider):
    """No-op STT provider for testing/offline mode."""

    def __init__(self, config: STTConfig):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        logger.info("Placeholder STT provider initialized")
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def transcribe(self, audio_data: bytes, sample_rate: int = 16000) -> SpeechResult:
        return SpeechResult(
            text="[placeholder] transcribed text",
            confidence=1.0,
            provider="placeholder",
        )

    async def transcribe_stream(self, audio_stream) -> SpeechResult:
        return SpeechResult(
            text="[placeholder] streamed transcription",
            confidence=1.0,
            provider="placeholder",
        )

    @property
    def name(self) -> STTProvider:
        return STTProvider.PLACEHOLDER

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()


class PlaceholderTTSProvider(BaseTTSProvider):
    """No-op TTS provider for testing/offline mode."""

    def __init__(self, config: TTSConfig):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        logger.info("Placeholder TTS provider initialized")
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def synthesize(self, request) -> VoiceResponse:
        # Generate silent audio as placeholder
        duration = len(request.text) * 50  # rough estimate
        silent_audio = b"\x00" * int(16000 * 2 * duration / 1000)  # 16-bit PCM
        return VoiceResponse(
            audio_data=silent_audio,
            duration_ms=duration,
            provider="placeholder",
        )

    async def synthesize_stream(self, request):
        # Yield empty chunks as placeholder
        for _ in range(10):
            yield b"\x00" * 1024

    @property
    def name(self) -> TTSProvider:
        return TTSProvider.PLACEHOLDER

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(supported_voices=["placeholder"])


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

    @property
    def name(self) -> WakeWordEngine:
        return WakeWordEngine.PLACEHOLDER

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities()


# Provider registries with lazy import support
_stt_providers: Dict[STTProvider, Any] = {
    STTProvider.PLACEHOLDER: PlaceholderSTTProvider,
    STTProvider.VOSK: "src.nova.voice.stt.VoskSTTProvider",
    STTProvider.WHISPER: "src.nova.voice.stt.WhisperSTTProvider",
    STTProvider.FASTER_WHISPER: "src.nova.voice.stt.FasterWhisperSTTProvider",
    STTProvider.WHISPER_CPP: "src.nova.voice.stt.WhisperCppSTTProvider",
}

_tts_providers: Dict[TTSProvider, Any] = {
    TTSProvider.PLACEHOLDER: PlaceholderTTSProvider,
    TTSProvider.PIPER: "src.nova.voice.tts.PiperTTSProvider",
    TTSProvider.ELEVENLABS: "src.nova.voice.tts.ElevenLabsTTSProvider",
    TTSProvider.WINDOWS_SAPI: "src.nova.voice.tts.WindowsSAPIProvider",
    TTSProvider.COQUI: "src.nova.voice.tts.CoquiTTSProvider",
}

_wakeword_providers: Dict[WakeWordEngine, Any] = {
    WakeWordEngine.PLACEHOLDER: PlaceholderWakeWordProvider,
    WakeWordEngine.VOSK: "src.nova.voice.wake_word.VoskWakeWordProvider",
    WakeWordEngine.PRECISE: "src.nova.voice.wake_word.PreciseWakeWordProvider",
}


def _import_provider(class_path: str):
    """Import provider class from string path."""
    module_path, class_name = class_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def _get_provider_class(registry: Dict, key):
    """Get provider class, importing if necessary."""
    class_path = registry.get(key)
    if not class_path:
        return None
    if isinstance(class_path, str):
        # Lazy import
        cls = _import_provider(class_path)
        registry[key] = cls
        return cls
    return class_path


def register_stt_provider(provider_type: STTProvider, provider_class: type) -> None:
    """Register a new STT provider implementation."""
    _stt_providers[provider_type] = provider_class


def register_tts_provider(provider_type: TTSProvider, provider_class: type) -> None:
    """Register a new TTS provider implementation."""
    _tts_providers[provider_type] = provider_class


def register_wakeword_provider(engine_type: WakeWordEngine, provider_class: type) -> None:
    """Register a new wake-word provider implementation."""
    _wakeword_providers[engine_type] = provider_class


def create_stt_provider(config: STTConfig) -> BaseSTTProvider:
    """Factory function to create STT provider instance."""
    provider_class = _get_provider_class(_stt_providers, config.provider)
    if not provider_class:
        raise ProviderError(
            f"Unknown STT provider: {config.provider}",
            provider=config.provider.value,
        )
    return provider_class(config)


def create_tts_provider(config: TTSConfig) -> BaseTTSProvider:
    """Factory function to create TTS provider instance."""
    provider_class = _get_provider_class(_tts_providers, config.provider)
    if not provider_class:
        raise ProviderError(
            f"Unknown TTS provider: {config.provider}",
            provider=config.provider.value,
        )
    return provider_class(config)


def create_wakeword_provider(config: WakeWordConfig) -> BaseWakeWordProvider:
    """Factory function to create wake-word provider instance."""
    provider_class = _get_provider_class(_wakeword_providers, config.engine)
    if not provider_class:
        raise ProviderError(
            f"Unknown wake-word engine: {config.engine}",
            provider=config.engine.value,
        )
    return provider_class(config)


def get_available_stt_providers() -> List[STTProvider]:
    return list(_stt_providers.keys())


def get_available_tts_providers() -> List[TTSProvider]:
    return list(_tts_providers.keys())


def get_available_wakeword_engines() -> List[WakeWordEngine]:
    return list(_wakeword_providers.keys())