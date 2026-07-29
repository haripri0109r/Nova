"""
Speech-to-Text abstraction.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncIterator, List
from dataclasses import dataclass
from pathlib import Path

from .types import STTProvider, STTConfig, AudioConfig
from .models import SpeechResult
from .exceptions import STTError

logger = logging.getLogger("nova.voice.stt")


@dataclass
class STTCapabilities:
    """Capabilities of an STT provider."""
    supports_streaming: bool = False
    supports_vad: bool = False
    supports_diarization: bool = False
    supported_languages: List[str] = None
    sample_rates: List[int] = None
    max_audio_length_seconds: int = 60

    def __post_init__(self):
        if self.supported_languages is None:
            self.supported_languages = ["en-US", "en-GB", "es-ES", "fr-FR", "de-DE"]
        if self.sample_rates is None:
            self.sample_rates = [8000, 16000, 22050, 44100, 48000]


class BaseSTTProvider(ABC):
    """Abstract base class for STT providers."""

    def __init__(self, config: STTConfig, audio_config: Optional[AudioConfig] = None):
        self.config = config
        self.audio_config = audio_config or AudioConfig()
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
    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        """Transcribe complete audio buffer."""
        pass

    @abstractmethod
    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[SpeechResult]:
        """Transcribe streaming audio."""
        pass

    @abstractmethod
    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        """Transcribe audio file."""
        pass

    @property
    @abstractmethod
    def name(self) -> STTProvider:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> STTCapabilities:
        """Provider capabilities."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class PlaceholderSTTProvider(BaseSTTProvider):
    """Placeholder STT provider for testing/offline mode."""

    def __init__(self, config: STTConfig, audio_config: Optional[AudioConfig] = None):
        super().__init__(config, audio_config)

    async def initialize(self) -> bool:
        self._initialized = True
        logger.info("Placeholder STT provider initialized")
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        return SpeechResult(
            text="[placeholder] transcribed text",
            confidence=1.0,
            language=language or "en",
            provider="placeholder",
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[SpeechResult]:
        yield SpeechResult(
            text="[placeholder] streaming transcription",
            confidence=1.0,
            language="en",
            provider="placeholder",
        )

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        return SpeechResult(
            text="[placeholder] file transcription",
            confidence=1.0,
            language=language or "en",
            provider="placeholder",
        )

    @property
    def name(self) -> STTProvider:
        return STTProvider.PLACEHOLDER

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities()


class VoskSTTProvider(BaseSTTProvider):
    """Vosk-based offline STT provider."""

    def __init__(self, config: STTConfig, audio_config: Optional[AudioConfig] = None):
        super().__init__(config, audio_config)
        self._model = None
        self._recognizer = None

    async def initialize(self) -> bool:
        try:
            from vosk import Model, KaldiRecognizer

            if not self.config.model_path:
                raise STTError("Vosk model path not configured")

            self._model = Model(self.config.model_path)
            self._initialized = True
            logger.info("Vosk STT provider initialized")
            return True

        except ImportError:
            logger.warning("vosk not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Vosk STT: {e}")
            return False

    async def cleanup(self) -> None:
        self._model = None
        self._initialized = False

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        from vosk import KaldiRecognizer
        import json

        if not self._model:
            raise STTError("Vosk model not loaded")

        rec = KaldiRecognizer(self._model, sample_rate)
        rec.AcceptWaveform(audio_data)

        result = json.loads(rec.Result())
        text = result.get("text", "")
        confidence = result.get("confidence", 0.0)

        return SpeechResult(
            text=text,
            confidence=confidence,
            language=language or "en",
            provider="vosk",
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[SpeechResult]:
        from vosk import KaldiRecognizer
        import json

        if not self._model:
            raise STTError("Vosk model not loaded")

        rec = KaldiRecognizer(self._model, sample_rate)

        async for chunk in audio_stream:
            if rec.AcceptWaveform(chunk):
                result = json.loads(rec.Result())
                text = result.get("text", "")
                if text:
                    yield SpeechResult(
                        text=text,
                        confidence=result.get("confidence", 0.0),
                        language="en",
                        provider="vosk",
                    )

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        import wave

        with wave.open(str(file_path), "rb") as wf:
            audio_data = wf.readframes(wf.getnframes())
            sample_rate = wf.getframerate()

        return await self.transcribe(audio_data, sample_rate, language)

    @property
    def name(self) -> STTProvider:
        return STTProvider.VOSK

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            supports_streaming=True,
            supported_languages=["en", "es", "fr", "de", "ru", "zh"],
            sample_rates=[8000, 16000],
            max_audio_length_seconds=3600,
        )


class WhisperSTTProvider(BaseSTTProvider):
    """OpenAI Whisper STT provider."""

    def __init__(self, config: STTConfig, audio_config: Optional[AudioConfig] = None):
        super().__init__(config, audio_config)
        self._model = None
        self._model_name = config.extra.get("model", "base")

    async def initialize(self) -> bool:
        try:
            import whisper

            self._model = whisper.load_model(self._model_name)
            self._initialized = True
            logger.info(f"Whisper STT provider initialized (model: {self._model_name})")
            return True

        except ImportError:
            logger.warning("openai-whisper not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Whisper: {e}")
            return False

    async def cleanup(self) -> None:
        self._model = None
        self._initialized = False

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        if not self._model:
            raise STTError("Whisper model not loaded")

        # Save to temp file for whisper
        import tempfile
        import soundfile as sf
        import numpy as np

        # Convert bytes to numpy array
        audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            import soundfile as sf
            sf.write(tmp.name, audio_data, samplerate=16000)
            result = self._model.transcribe(tmp.name, language=language)

        return SpeechResult(
            text=result["text"],
            confidence=1.0,  # Whisper doesn't provide confidence directly
            language=result.get("language", language or "en"),
            duration_ms=result.get("duration", 0) * 1000,
            provider="whisper",
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[SpeechResult]:
        # Whisper doesn't natively support streaming - buffer and process
        raise NotImplementedError("Streaming not yet implemented for Whisper")

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        if not self._model:
            raise STTError("Whisper model not loaded")

        result = self._model.transcribe(str(file_path), language=language)

        return SpeechResult(
            text=result["text"],
            confidence=1.0,
            language=result.get("language", language or "en"),
            duration_ms=result.get("duration", 0) * 1000,
            provider="whisper",
        )

    @property
    def name(self) -> STTProvider:
        return STTProvider.WHISPER

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            supports_streaming=False,
            supported_languages=whisper.tokenizer.LANGUAGES.keys() if self._model else ["en"],
            sample_rates=[16000],
            max_audio_length_seconds=1800,
        )


class FasterWhisperSTTProvider(BaseSTTProvider):
    """Faster-Whisper STT provider (optimized Whisper)."""

    def __init__(self, config: STTConfig, audio_config: Optional[AudioConfig] = None):
        super().__init__(config, audio_config)
        self._model = None
        self._model_name = config.extra.get("model", "base.en")

    async def initialize(self) -> bool:
        try:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(
                self._model_name,
                device="cpu",
                compute_type="int8",
            )
            self._initialized = True
            logger.info(f"Faster-Whisper STT provider initialized (model: {self._model_name})")
            return True

        except ImportError:
            logger.warning("faster-whisper not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Faster-Whisper: {e}")
            return False

    async def cleanup(self) -> None:
        self._model = None
        self._initialized = False

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        if not self._model:
            raise STTError("Faster-Whisper model not loaded")

        import tempfile
        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio_data, samplerate=sample_rate)

            segments, info = self._model.transcribe(
                tmp.name,
                language=language,
                beam_size=5,
                vad_filter=True,
            )

            text = " ".join([seg.text for seg in segments])

            return SpeechResult(
                text=text,
                confidence=1.0,
                language=info.language or language or "en",
                duration_ms=info.duration * 1000,
                provider="faster_whisper",
            )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[SpeechResult]:
        raise NotImplementedError("Streaming not yet implemented for Faster-Whisper")

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        segments, info = self._model.transcribe(
            str(file_path),
            language=language,
            beam_size=5,
            vad_filter=True,
        )

        text = " ".join([seg.text for seg in segments])

        return SpeechResult(
            text=text,
            confidence=1.0,
            language=info.language or language or "en",
            duration_ms=info.duration * 1000,
            provider="faster_whisper",
        )

    @property
    def name(self) -> STTProvider:
        return STTProvider.FASTER_WHISPER

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            supports_streaming=False,
            supported_languages=["en", "es", "fr", "de", "it", "pt", "ru", "zh", "ja", "ko"],
            sample_rates=[16000],
            max_audio_length_seconds=3600,
        )


class WhisperCppSTTProvider(BaseSTTProvider):
    """Whisper.cpp STT provider."""

    def __init__(self, config: STTConfig, audio_config: Optional[AudioConfig] = None):
        super().__init__(config, audio_config)
        self._model = None

    async def initialize(self) -> bool:
        try:
            from whisper_cpp_python import Whisper

            model_path = self.config.model_path or "models/ggml-base.en.bin"
            self._model = Whisper(model_path)
            self._initialized = True
            logger.info("Whisper.cpp STT provider initialized")
            return True

        except ImportError:
            logger.warning("whisper-cpp-python not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Whisper.cpp: {e}")
            return False

    async def cleanup(self) -> None:
        self._model = None
        self._initialized = False

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        if not self._model:
            raise STTError("Whisper.cpp model not loaded")

        import tempfile
        import soundfile as sf

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            sf.write(tmp.name, audio_data, samplerate=sample_rate)
            result = self._model.transcribe(tmp.name, language=language)

        return SpeechResult(
            text=result.get("text", ""),
            confidence=1.0,
            language=result.get("language", language or "en"),
            provider="whisper_cpp",
        )

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterator[bytes],
        sample_rate: int = 16000,
    ) -> AsyncIterator[SpeechResult]:
        raise NotImplementedError("Streaming not yet implemented")

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        if not self._model:
            raise STTError("Whisper.cpp model not loaded")

        result = self._model.transcribe(str(file_path), language=language)

        return SpeechResult(
            text=result.get("text", ""),
            confidence=1.0,
            language=result.get("language", language or "en"),
            provider="whisper_cpp",
        )

    @property
    def name(self) -> STTProvider:
        return STTProvider.WHISPER_CPP

    @property
    def capabilities(self) -> STTCapabilities:
        return STTCapabilities(
            supported_languages=["en", "es", "fr", "de", "it", "pt", "ru", "zh", "ja", "ko"],
            sample_rates=[16000],
            max_audio_length_seconds=3600,
        )


# Provider registry
_stt_providers: Dict[STTProvider, type] = {
    STTProvider.PLACEHOLDER: PlaceholderSTTProvider,
    STTProvider.VOSK: VoskSTTProvider,
    STTProvider.WHISPER: WhisperSTTProvider,
    STTProvider.FASTER_WHISPER: FasterWhisperSTTProvider,
    STTProvider.WHISPER_CPP: WhisperCppSTTProvider,
}


def register_stt_provider(provider_type: STTProvider, provider_class: type) -> None:
    """Register a new STT provider implementation."""
    _stt_providers[provider_type] = provider_class


def create_stt_provider(config: STTConfig, audio_config: Optional[AudioConfig] = None) -> BaseSTTProvider:
    """Factory function to create STT provider instance."""
    provider_class = _stt_providers.get(config.provider)
    if not provider_class:
        raise STTError(
            f"Unknown STT provider: {config.provider}",
            provider=config.provider.value,
        )
    return provider_class(config, audio_config)


def get_available_stt_providers() -> List[STTProvider]:
    return list(_stt_providers.keys())


# High-level STT interface
class STTService:
    """High-level STT interface."""

    def __init__(
        self,
        provider: STTProvider = STTProvider.PLACEHOLDER,
        config: Optional[STTConfig] = None,
        audio_config: Optional[AudioConfig] = None,
    ):
        self._provider = create_stt_provider(config or STTConfig(provider=provider), audio_config)

    async def initialize(self) -> bool:
        return await self._provider.initialize()

    async def cleanup(self) -> None:
        await self._provider.cleanup()

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        return await self._provider.transcribe(audio_data, sample_rate, language)

    async def transcribe_stream(
        self,
        audio_stream,
        sample_rate: int = 16000,
    ):
        async for result in self._provider.transcribe_stream(audio_stream, sample_rate):
            yield result

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        return await self._provider.transcribe_file(file_path, language)

    @property
    def name(self) -> STTProvider:
        return self._provider.name

    @property
    def is_initialized(self) -> bool:
        return self._provider.is_initialized


# Global instance
_stt_service: Optional[STTService] = None


def get_stt_provider(
    provider: STTProvider = STTProvider.PLACEHOLDER,
    config: Optional[STTConfig] = None,
    audio_config: Optional[AudioConfig] = None,
) -> STTService:
    """Get or create global STT provider instance."""
    global _stt_service
    if _stt_service is None:
        _stt_service = STTService(provider, config, audio_config)
    return _stt_service