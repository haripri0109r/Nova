"""
Voice Engine - Public API for voice operations.
"""
from __future__ import annotations

import logging
from typing import Optional, List
from dataclasses import dataclass, field
from pathlib import Path

from .types import (
    VoiceEngineConfig,
    VoiceState,
    WakeWordState,
    AudioConfig,
    STTConfig,
    TTSConfig,
    WakeWordConfig,
)
from .models import (
    SpeechResult,
    VoiceResponse,
    VoiceRequest,
    WakeWordResult,
    VoiceEngineHealth,
)
from .manager import VoiceManager, get_voice_manager, VoiceManagerConfig
from .exceptions import VoiceEngineError

logger = logging.getLogger("nova.voice.engine")


@dataclass
class VoiceEngineConfig:
    """Configuration for the Voice Engine."""
    audio_config: AudioConfig = None
    stt_config: STTConfig = None
    tts_config: TTSConfig = None
    wake_word_config: WakeWordConfig = None
    auto_initialize: bool = True


class VoiceEngine:
    """
    High-level Voice Engine API.

    Provides a unified interface for all voice operations:
    - Speech-to-Text (STT)
    - Text-to-Speech (TTS)
    - Wake-word detection
    - Audio recording/playback
    """

    def __init__(self, config: VoiceEngineConfig = None):
        self.config = config or VoiceEngineConfig()
        self._manager: Optional[VoiceManager] = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize the voice engine and all components."""
        if self._initialized:
            return True

        logger.info("Initializing Voice Engine...")

        try:
            manager_config = VoiceManagerConfig(
                audio_config=self.config.audio_config,
                stt_config=self.config.stt_config,
                tts_config=self.config.tts_config,
                wake_word_config=self.config.wake_word_config,
            )
            self._manager = get_voice_manager(manager_config)
            await self._manager.initialize()
            self._initialized = True
            logger.info("Voice Engine initialized successfully")
            return True
        except Exception as e:
            logger.error(f"Failed to initialize Voice Engine: {e}")
            raise VoiceEngineError(f"Initialization failed: {e}") from e

    async def cleanup(self) -> None:
        """Cleanup all resources."""
        if self._manager:
            await self._manager.cleanup()
        self._initialized = False
        logger.info("Voice Engine cleaned up")

    # --- STT Operations ---

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        """Transcribe audio to text."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.transcribe(audio_data, sample_rate, language)

    async def transcribe_stream(
        self,
        audio_stream,
        sample_rate: int = 16000,
    ):
        """Transcribe streaming audio."""
        if not self._initialized:
            await self.initialize()
        async for result in self._manager.transcribe_stream(audio_stream, sample_rate):
            yield result

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        """Transcribe audio file."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.transcribe_file(file_path, language)

    # --- TTS Operations ---

    async def speak(self, request: VoiceRequest) -> VoiceResponse:
        """Speak text using TTS."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.speak(request)

    async def speak_stream(self, request: VoiceRequest):
        """Stream synthesized audio."""
        if not self._initialized:
            await self.initialize()
        async for chunk in self._manager.speak_stream(request):
            yield chunk

    async def speak_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        """Synthesize speech and save to file."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.speak_to_file(request, file_path)

    async def speak_text(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> VoiceResponse:
        """Convenience method to speak text."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.speak_text(text, voice, speed, volume)

    # --- Wake Word Operations ---

    async def start_wake_word_detection(self) -> None:
        """Start listening for wake word."""
        if not self._initialized:
            await self.initialize()
        await self._manager.start_wake_word_detection()

    async def stop_wake_word_detection(self) -> None:
        """Stop listening for wake word."""
        if self._initialized:
            await self._manager.stop_wake_word_detection()

    async def process_wake_word(self, audio_data: bytes) -> WakeWordResult:
        """Process audio for wake word detection."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.process_wake_word(audio_data)

    def on_wake_word(self, callback: callable) -> None:
        """Register callback for wake word detection."""
        if self._manager:
            self._manager.on_wake_word(callback)

    # --- Audio Operations ---

    async def record(self, duration: float) -> bytes:
        """Record audio for specified duration."""
        if not self._initialized:
            await self.initialize()
        return await self._manager.record(duration)

    async def play(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        """Play audio data."""
        if not self._initialized:
            await self.initialize()
        await self._manager.play(audio_data, sample_rate)

    async def play_file(self, file_path: Path) -> None:
        """Play audio file."""
        if not self._initialized:
            await self.initialize()
        await self._manager.play_file(file_path)

    def list_audio_devices(self) -> List:
        """List available audio devices."""
        if self._manager:
            return self._manager.list_audio_devices()
        return []

    # --- Event System ---

    def on(self, event: str, callback: callable) -> None:
        """Register event callback."""
        if self._manager:
            self._manager.on(event, callback)

    def off(self, event: str, callback: callable) -> None:
        """Unregister event callback."""
        if self._manager:
            self._manager.off(event, callback)

    # --- Health & Status ---

    async def health_check(self) -> VoiceEngineHealth:
        """Perform health check on all components."""
        if self._manager:
            return await self._manager.health_check()
        return VoiceEngineHealth(
            status="uninitialized",
            state=VoiceState.IDLE,
            wake_word_state=WakeWordState.DORMANT,
        )

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def state(self) -> VoiceState:
        return self._manager.state if self._manager else VoiceState.IDLE

    @property
    def wake_word_state(self) -> WakeWordState:
        return self._manager.wake_word_state if self._manager else WakeWordState.DORMANT


# Global instance
_voice_engine: Optional[VoiceEngine] = None


def get_voice_engine(config: Optional[VoiceEngineConfig] = None) -> VoiceEngine:
    """Get or create the global VoiceEngine instance."""
    global _voice_engine
    if _voice_engine is None:
        _voice_engine = VoiceEngine(config)
    return _voice_engine