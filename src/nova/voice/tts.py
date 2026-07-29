"""
Text-to-Speech abstraction for speech synthesis.
"""
from __future__ import annotations

import logging
import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, List, Dict, Any, AsyncIterator
from pathlib import Path

from .models import VoiceResponse, VoiceRequest
from .types import TTSProvider, TTSConfig
from .exceptions import TTSError

logger = logging.getLogger("nova.voice.tts")


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
    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        """Synthesize speech from text."""
        pass

    @abstractmethod
    async def synthesize_stream(
        self,
        request: VoiceRequest,
    ) -> AsyncIterator[bytes]:
        """Stream synthesized audio chunks."""
        pass

    @abstractmethod
    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        """Synthesize speech and save to file."""
        pass

    @property
    @abstractmethod
    def name(self) -> TTSProvider:
        """Provider identifier."""
        pass

    @property
    @abstractmethod
    def capabilities(self) -> TTSCCapabilities:
        """Provider capabilities."""
        pass

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class PlaceholderTTSProvider(BaseTTSProvider):
    """Placeholder TTS provider for testing/offline mode."""

    def __init__(self, config: TTSConfig):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        logger.info("Placeholder TTS provider initialized")
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        # Generate silent audio as placeholder
        import numpy as np

        duration = len(request.text) * 50  # ~50ms per character
        sample_rate = 22050
        samples = int(sample_rate * duration / 1000)
        silent_audio = np.zeros(samples, dtype=np.int16).tobytes()

        return VoiceResponse(
            audio_data=silent_audio,
            format=request.format,
            sample_rate=sample_rate,
            duration_ms=duration,
            provider="placeholder",
        )

    async def synthesize_stream(self, request: VoiceRequest) -> AsyncIterator[bytes]:
        # Yield silent chunks
        for _ in range(10):
            yield b"\x00" * 1024
            await asyncio.sleep(0.01)

    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        response = await self.synthesize(request)
        import soundfile as sf
        import numpy as np

        audio_array = np.frombuffer(response.audio_data, dtype=np.int16)
        sf.write(file_path, audio_array, response.sample_rate)
        return response

    @property
    def name(self) -> TTSProvider:
        return TTSProvider.PLACEHOLDER

    @property
    def capabilities(self) -> TTSCCapabilities:
        return TTSCCapabilities()


class PiperTTSProvider(BaseTTSProvider):
    """Piper TTS provider (fast, local, high-quality)."""

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self._piper = None
        self._voice_model = config.extra.get("voice", "en_US-lessac-medium")

    async def initialize(self) -> bool:
        try:
            from piper import PiperVoice

            self._piper = PiperVoice.load(self._voice_model)
            self._initialized = True
            logger.info(f"Piper TTS provider initialized (voice: {self._voice_model})")
            return True

        except ImportError:
            logger.warning("piper-tts not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Piper TTS: {e}")
            return False

    async def cleanup(self) -> None:
        self._piper = None
        self._initialized = False

    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        import io
        import numpy as np

        if not self._piper:
            raise TTSError("Piper voice not loaded")

        audio_bytes = io.BytesIO()
        self._piper.synthesize(
            request.text,
            audio_bytes,
            speaker_id=0,
            length_scale=1.0 / request.speed,
            noise_scale=0.667,
            noise_w=0.8,
        )

        audio_data = audio_bytes.getvalue()

        return VoiceResponse(
            audio_data=audio_data,
            format=request.format,
            sample_rate=self._piper.config.sample_rate,
            duration_ms=len(audio_data) / (self._piper.config.sample_rate * 2) * 1000,
            provider="piper",
        )

    async def synthesize_stream(self, request: VoiceRequest) -> AsyncIterator[bytes]:
        import io

        if not self._piper:
            raise TTSError("Piper voice not loaded")

        audio_buffer = io.BytesIO()
        for chunk in self._piper.synthesize_stream(
            request.text,
            speaker_id=0,
            length_scale=1.0 / request.speed,
        ):
            audio_buffer.write(chunk)
            yield chunk
            await asyncio.sleep(0)

    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        response = await self.synthesize(request)
        import soundfile as sf
        import numpy as np

        audio_array = np.frombuffer(response.audio_data, dtype=np.int16)
        sf.write(file_path, audio_array, response.sample_rate)
        return response

    @property
    def name(self) -> TTSProvider:
        return TTSProvider.PIPER

    @property
    def capabilities(self) -> TTSCCapabilities:
        return TTSCCapabilities(
            supports_streaming=True,
            supported_voices=["en_US-lessac-medium", "en_US-amy-low", "en_GB-alan-low"],
            supported_formats=["wav"],
            max_text_length=5000,
            sample_rates=[22050],
        )


class ElevenLabsTTSProvider(BaseTTSProvider):
    """ElevenLabs cloud TTS provider."""

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self._client = None

    async def initialize(self) -> bool:
        try:
            from elevenlabs import generate, set_api_key

            if not self.config.extra.get("api_key"):
                raise TTSError("ElevenLabs API key not configured")

            set_api_key(self.config.extra["api_key"])
            self._initialized = True
            logger.info("ElevenLabs TTS provider initialized")
            return True

        except ImportError:
            logger.warning("elevenlabs not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs: {e}")
            return False

    async def cleanup(self) -> None:
        self._initialized = False

    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        from elevenlabs import generate

        if not self._initialized:
            raise TTSError("ElevenLabs not initialized")

        audio_data = generate(
            text=request.text,
            voice=request.voice or self.config.voice,
            model="eleven_monolingual_v1",
            stream=False,
        )

        return VoiceResponse(
            audio_data=audio_data,
            format=request.format,
            sample_rate=22050,
            duration_ms=len(request.text) * 50,
            provider="elevenlabs",
        )

    async def synthesize_stream(self, request: VoiceRequest) -> AsyncIterator[bytes]:
        from elevenlabs import generate

        for chunk in generate(
            text=request.text,
            voice=request.voice or self.config.voice,
            model="eleven_monolingual_v1",
            stream=True,
        ):
            yield chunk
            await asyncio.sleep(0)

    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        from elevenlabs import generate
        import soundfile as sf
        import numpy as np

        audio_data = generate(
            text=request.text,
            voice=request.voice or self.config.voice,
            model="eleven_monolingual_v1",
            stream=False,
        )

        sf.write(file_path, audio_data, 22050)

        return VoiceResponse(
            audio_data=audio_data,
            format=request.format,
            sample_rate=22050,
            duration_ms=len(request.text) * 50,
            provider="elevenlabs",
        )

    @property
    def name(self) -> TTSProvider:
        return TTSProvider.ELEVENLABS

    @property
    def capabilities(self) -> TTSCCapabilities:
        return TTSCCapabilities(
            supports_streaming=True,
            supported_voices=["rachel", "clyde", "domi", "dave", "fin"],
            supported_formats=["wav", "mp3"],
            max_text_length=2500,
            sample_rates=[22050, 44100],
        )


class WindowsSAPIProvider(BaseTTSProvider):
    """Windows SAPI TTS provider (built-in Windows TTS)."""

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self._speaker = None

    async def initialize(self) -> bool:
        try:
            import win32com.client

            self._speaker = win32com.client.Dispatch("SAPI.SpVoice")
            self._initialized = True
            logger.info("Windows SAPI TTS provider initialized")
            return True

        except ImportError:
            logger.warning("pywin32 not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize SAPI: {e}")
            return False

    async def cleanup(self) -> None:
        self._speaker = None
        self._initialized = False

    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        import tempfile
        import soundfile as sf
        import numpy as np

        if not self._speaker:
            raise TTSError("SAPI speaker not initialized")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            self._speaker.Rate = int((request.speed - 1.0) * 10)
            self._speaker.Volume = int(request.volume * 100)
            self._speaker.AudioOutputStream = None  # Use default
            self._speaker.Speak(request.text)

            # SAPI doesn't directly give audio data - use SpFileStream
            # This is a simplified implementation
            import pythoncom
            from comtypes.client import CreateObject

            stream = CreateObject("SAPI.SpFileStream")
            stream.Open(tmp.name, 3)  # SSFMCreateForWrite
            self._speaker.AudioOutputStream = stream
            self._speaker.Speak(request.text)
            stream.Close()

            import soundfile as sf
            audio_data, sr = sf.read(tmp.name)

            return VoiceResponse(
                audio_data=audio_data.tobytes(),
                format=request.format,
                sample_rate=sr,
                duration_ms=len(request.text) * 50,
                provider="windows_sapi",
            )

    async def synthesize_stream(self, request: VoiceRequest) -> AsyncIterator[bytes]:
        raise NotImplementedError("Streaming not supported for SAPI")

    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        import tempfile
        import soundfile as sf
        import numpy as np

        if not self._speaker:
            raise TTSError("SAPI speaker not initialized")

        import pythoncom
        from comtypes.client import CreateObject

        stream = CreateObject("SAPI.SpFileStream")
        stream.Open(str(file_path), 3)  # SSFMCreateForWrite
        self._speaker.AudioOutputStream = stream
        self._speaker.Speak(request.text)
        stream.Close()

        audio_data, sr = sf.read(file_path)

        return VoiceResponse(
            audio_data=audio_data.tobytes(),
            format=request.format,
            sample_rate=sr,
            duration_ms=len(request.text) * 50,
            provider="windows_sapi",
        )

    @property
    def name(self) -> TTSProvider:
        return TTSProvider.WINDOWS_SAPI

    @property
    def capabilities(self) -> TTSCCapabilities:
        return TTSCCapabilities(
            supported_voices=["Microsoft David", "Microsoft Zira", "Microsoft Mark"],
            supported_formats=["wav"],
            max_text_length=10000,
            sample_rates=[22050],
        )


class CoquiTTSProvider(BaseTTSProvider):
    """Coqui TTS provider (open-source neural TTS)."""

    def __init__(self, config: TTSConfig):
        super().__init__(config)
        self._tts = None

    async def initialize(self) -> bool:
        try:
            from TTS.api import TTS

            model_name = self.config.extra.get("model", "tts_models/en/ljspeech/tacotron2-DDC")
            self._tts = TTS(model_name)
            self._initialized = True
            logger.info(f"Coqui TTS provider initialized (model: {model_name})")
            return True

        except ImportError:
            logger.warning("TTS (Coqui) not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize Coqui TTS: {e}")
            return False

    async def cleanup(self) -> None:
        self._tts = None
        self._initialized = False

    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        import numpy as np

        if not self._tts:
            raise TTSError("Coqui TTS model not loaded")

        audio_array = self._tts.tts(
            text=request.text,
            speaker=request.voice,
            speed=request.speed,
        )

        # Convert to int16
        audio_data = (np.array(audio_array) * 32767).astype(np.int16).tobytes()

        return VoiceResponse(
            audio_data=audio_data,
            format=request.format,
            sample_rate=22050,
            duration_ms=len(request.text) * 50,
            provider="coqui",
        )

    async def synthesize_stream(self, request: VoiceRequest) -> AsyncIterator[bytes]:
        # Coqui TTS doesn't natively stream - yield chunks
        response = await self.synthesize(request)
        chunk_size = 1024
        for i in range(0, len(response.audio_data), chunk_size):
            yield response.audio_data[i:i+chunk_size]
            await asyncio.sleep(0)

    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        self._tts.tts_to_file(
            text=request.text,
            speaker=request.voice,
            file_path=str(file_path),
        )

        import soundfile as sf
        audio_data, sr = sf.read(file_path)

        return VoiceResponse(
            audio_data=audio_data.tobytes(),
            format=request.format,
            sample_rate=sr,
            duration_ms=len(request.text) * 50,
            provider="coqui",
        )

    @property
    def name(self) -> TTSProvider:
        return TTSProvider.COQUI

    @property
    def capabilities(self) -> TTSCCapabilities:
        return TTSCCapabilities(
            supports_streaming=False,
            supported_voices=["ljspeech", "vctk", "multi-lingual"],
            supported_formats=["wav"],
            max_text_length=1000,
            sample_rates=[22050],
        )


# Capabilities dataclass
@dataclass
class TTSCCapabilities:
    """Capabilities of a TTS provider."""
    supports_streaming: bool = False
    supported_voices: List[str] = None
    supported_formats: List[str] = None
    max_text_length: int = 5000
    sample_rates: List[int] = None

    def __post_init__(self):
        if self.supported_voices is None:
            self.supported_voices = ["default"]
        if self.supported_formats is None:
            self.supported_formats = ["wav"]
        if self.sample_rates is None:
            self.sample_rates = [16000, 22050, 24000]


# Provider registry
_tts_providers: Dict[TTSProvider, type] = {
    TTSProvider.PLACEHOLDER: PlaceholderTTSProvider,
    TTSProvider.PIPER: PiperTTSProvider,
    TTSProvider.ELEVENLABS: ElevenLabsTTSProvider,
    TTSProvider.WINDOWS_SAPI: WindowsSAPIProvider,
    TTSProvider.COQUI: CoquiTTSProvider,
}


def register_tts_provider(provider_type: TTSProvider, provider_class: type) -> None:
    """Register a new TTS provider implementation."""
    _tts_providers[provider_type] = provider_class


def create_tts_provider(config: TTSConfig) -> BaseTTSProvider:
    """Factory function to create TTS provider instance."""
    provider_class = _tts_providers.get(config.provider)
    if not provider_class:
        raise TTSError(
            f"Unknown TTS provider: {config.provider}",
            provider=config.provider.value,
        )
    return provider_class(config)


def get_available_tts_providers() -> List[TTSProvider]:
    return list(_tts_providers.keys())


# High-level TTS interface
class TTSService:
    """High-level TTS interface."""

    def __init__(
        self,
        provider: TTSProvider = TTSProvider.PLACEHOLDER,
        config: Optional[TTSConfig] = None,
    ):
        self._provider = create_tts_provider(config or TTSConfig(provider=provider))

    async def initialize(self) -> bool:
        return await self._provider.initialize()

    async def cleanup(self) -> None:
        await self._provider.cleanup()

    async def synthesize(self, request: VoiceRequest) -> VoiceResponse:
        return await self._provider.synthesize(request)

    async def synthesize_stream(self, request: VoiceRequest) -> AsyncIterator[bytes]:
        async for chunk in self._provider.synthesize_stream(request):
            yield chunk

    async def synthesize_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        return await self._provider.synthesize_to_file(request, file_path)

    @property
    def name(self) -> TTSProvider:
        return self._provider.name

    @property
    def is_initialized(self) -> bool:
        return self._provider.is_initialized


# Global instance
_tts_service: Optional[TTSService] = None


def get_tts_provider(
    provider: TTSProvider = TTSProvider.PLACEHOLDER,
    config: Optional[TTSConfig] = None,
) -> TTSService:
    """Get or create global TTS provider instance."""
    global _tts_service
    if _tts_service is None:
        _tts_service = TTSService(provider, config)
    return _tts_service