"""
Voice Manager - Coordinates all voice operations.
"""
from __future__ import annotations

import logging
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field

from .types import (
    VoiceEngineConfig,
    AudioConfig,
    STTConfig,
    TTSConfig,
    WakeWordConfig,
    STTProvider,
    TTSProvider,
    WakeWordEngine,
    VoiceState,
    WakeWordState,
)
from .models import (
    SpeechResult,
    VoiceResponse,
    VoiceRequest,
    WakeWordResult,
    VoiceEngineHealth,
)
from .audio import AudioManager, get_audio_manager
from .stt import STTProvider, get_stt_provider, BaseSTTProvider
from .tts import TTSProvider, get_tts_provider, BaseTTSProvider
from .wake_word import WakeWordDetector, get_wake_word_detector, BaseWakeWordProvider
from .exceptions import VoiceEngineError

logger = logging.getLogger("nova.voice.manager")


@dataclass
class VoiceManagerConfig:
    """Configuration for Voice Manager."""
    audio_config: AudioConfig = None
    stt_config: STTConfig = None
    tts_config: TTSConfig = None
    wake_word_config: WakeWordConfig = None
    auto_start: bool = True


class VoiceManager:
    """
    Central manager coordinating all voice operations.

    Responsibilities:
    - STT (Speech-to-Text) coordination
    - TTS (Text-to-Speech) coordination
    - Wake-word detection
    - Audio device management
    - Provider lifecycle
    """

    def __init__(self, config: VoiceManagerConfig = None):
        self.config = config or VoiceManagerConfig()
        self._audio: Optional[AudioManager] = None
        self._stt: Optional[STTProvider] = None
        self._tts: Optional[TTSProvider] = None
        self._wake_word: Optional[WakeWordDetector] = None
        self._state: VoiceState = VoiceState.IDLE
        self._wake_word_state: WakeWordState = WakeWordState.DORMANT
        self._initialized: bool = False
        self._callbacks: Dict[str, List[callable]] = {
            "on_speech": [],
            "on_wake_word": [],
            "on_state_change": [],
            "on_error": [],
        }

    async def initialize(self) -> bool:
        """Initialize all voice components."""
        if self._initialized:
            return True

        logger.info("Initializing Voice Manager...")

        try:
            # Initialize audio manager
            self._audio = get_audio_manager(self.config.audio_config)
            await self._audio.initialize()

            # Initialize STT provider
            self._stt = get_stt_provider(
                self.config.stt_config.provider if self.config.stt_config else STTProvider.PLACEHOLDER,
                self.config.stt_config,
                self.config.audio_config,
            )
            await self._stt.initialize()

            # Initialize TTS provider
            self._tts = get_tts_provider(
                self.config.tts_config.provider if self.config.tts_config else TTSProvider.PLACEHOLDER,
                self.config.tts_config,
            )
            await self._tts.initialize()

            # Initialize wake-word detector
            self._wake_word = get_wake_word_detector(
                self.config.wake_word_config.engine if self.config.wake_word_config else WakeWordEngine.PLACEHOLDER,
                self.config.wake_word_config,
            )
            await self._wake_word.initialize()

            self._initialized = True
            self._state = VoiceState.IDLE
            self._wake_word_state = WakeWordState.DORMANT

            logger.info("Voice Manager initialized successfully")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Voice Manager: {e}")
            raise VoiceEngineError(f"Manager initialization failed: {e}") from e

    async def cleanup(self) -> None:
        """Cleanup all voice components."""
        logger.info("Cleaning up Voice Manager...")

        if self._wake_word:
            await self._wake_word.cleanup()
        if self._tts:
            await self._tts.cleanup()
        if self._stt:
            await self._stt.cleanup()
        if self._audio:
            await self._audio.cleanup()

        self._initialized = False
        self._state = VoiceState.IDLE
        self._wake_word_state = WakeWordState.DORMANT
        logger.info("Voice Manager cleaned up")

    # --- STT Operations ---

    async def transcribe(
        self,
        audio_data: bytes,
        sample_rate: int = 16000,
        language: Optional[str] = None,
    ) -> SpeechResult:
        """Transcribe audio to text."""
        self._set_state(VoiceState.PROCESSING)
        try:
            result = await self._stt.transcribe(audio_data, sample_rate, language)
            self._emit("on_speech", result)
            return result
        finally:
            self._set_state(VoiceState.IDLE)

    async def transcribe_stream(
        self,
        audio_stream,
        sample_rate: int = 16000,
    ):
        """Transcribe streaming audio."""
        self._set_state(VoiceState.LISTENING)
        try:
            async for result in self._stt.transcribe_stream(audio_stream, sample_rate):
                self._emit("on_speech", result)
                yield result
        finally:
            self._set_state(VoiceState.IDLE)

    async def transcribe_file(
        self,
        file_path: Path,
        language: Optional[str] = None,
    ) -> SpeechResult:
        """Transcribe audio file."""
        self._set_state(VoiceState.PROCESSING)
        try:
            result = await self._stt.transcribe_file(file_path, language)
            self._emit("on_speech", result)
            return result
        finally:
            self._set_state(VoiceState.IDLE)

    # --- TTS Operations ---

    async def speak(self, request: VoiceRequest) -> VoiceResponse:
        """Speak text using TTS."""
        self._set_state(VoiceState.SPEAKING)
        try:
            result = await self._tts.synthesize(request)
            self._emit("on_speech", result)
            return result
        finally:
            self._set_state(VoiceState.IDLE)

    async def speak_stream(self, request: VoiceRequest):
        """Stream synthesized audio."""
        self._set_state(VoiceState.SPEAKING)
        try:
            async for chunk in self._tts.synthesize_stream(request):
                yield chunk
        finally:
            self._set_state(VoiceState.IDLE)

    async def speak_to_file(
        self,
        request: VoiceRequest,
        file_path: Path,
    ) -> VoiceResponse:
        """Synthesize speech and save to file."""
        self._set_state(VoiceState.SPEAKING)
        try:
            result = await self._tts.synthesize_to_file(request, file_path)
            self._emit("on_speech", result)
            return result
        finally:
            self._set_state(VoiceState.IDLE)

    async def speak_text(
        self,
        text: str,
        voice: Optional[str] = None,
        speed: float = 1.0,
        volume: float = 1.0,
    ) -> VoiceResponse:
        """Convenience method to speak text."""
        request = VoiceRequest(
            text=text,
            voice=voice,
            speed=speed,
            volume=volume,
        )
        return await self.speak(request)

    # --- Wake Word Operations ---

    async def start_wake_word_detection(self) -> None:
        """Start listening for wake word."""
        self._wake_word_state = WakeWordState.ACTIVE
        await self._wake_word.start()

    async def stop_wake_word_detection(self) -> None:
        """Stop listening for wake word."""
        self._wake_word_state = WakeWordState.DORMANT
        await self._wake_word.stop()

    async def process_wake_word(self, audio_data: bytes) -> WakeWordResult:
        """Process audio for wake word detection."""
        result = await self._wake_word.process(audio_data)
        if result.detected:
            self._wake_word_state = WakeWordState.DETECTED
            self._emit("on_wake_word", result)
        return result

    def on_wake_word(self, callback: callable) -> None:
        """Register callback for wake word detection."""
        self._wake_word.on_wake_word(callback)

    # --- Audio Operations ---

    async def record(self, duration: float) -> bytes:
        """Record audio for specified duration."""
        return await self._audio.record(duration)

    async def play(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        """Play audio data."""
        await self._audio.play(audio_data, sample_rate)

    async def play_file(self, file_path: Path) -> None:
        """Play audio file."""
        await self._audio.play_file(file_path)

    def list_audio_devices(self) -> List:
        """List available audio devices."""
        return self._audio.list_devices()

    # --- State Management ---

    def _set_state(self, state: VoiceState) -> None:
        """Update voice state and emit change event."""
        old_state = self._state
        self._state = state
        if old_state != state:
            self._emit("on_state_change", {"old": old_state, "new": state})

    def _emit(self, event: str, data: Any) -> None:
        """Emit event to registered callbacks."""
        for callback in self._callbacks.get(event, []):
            try:
                callback(data)
            except Exception as e:
                logger.warning(f"Callback error for {event}: {e}")

    def on(self, event: str, callback: callable) -> None:
        """Register event callback."""
        if event in self._callbacks:
            self._callbacks[event].append(callback)

    def off(self, event: str, callback: callable) -> None:
        """Unregister event callback."""
        if event in self._callbacks and callback in self._callbacks[event]:
            self._callbacks[event].remove(callback)

    # --- Health & Status ---

    async def health_check(self) -> VoiceEngineHealth:
        """Perform health check on all components."""
        errors = []

        stt_ok = self._stt.is_initialized if self._stt else False
        tts_ok = self._tts.is_initialized if self._tts else False
        ww_ok = self._wake_word.is_initialized if self._wake_word else False
        audio_ok = self._audio._initialized if self._audio else False

        if not stt_ok:
            errors.append("STT provider not initialized")
        if not tts_ok:
            errors.append("TTS provider not initialized")
        if not ww_ok:
            errors.append("Wake-word detector not initialized")
        if not audio_ok:
            errors.append("Audio manager not initialized")

        return VoiceEngineHealth(
            status="healthy" if not errors else "degraded",
            state=self._state,
            wake_word_state=self._wake_word_state,
            audio_device=self._audio.get_default_input_device().name if self._audio and self._audio.get_default_input_device() else None,
            stt_provider=self._stt.name.value if self._stt else None,
            tts_provider=self._tts.name.value if self._tts else None,
            wake_word_engine=self._wake_word.name.value if self._wake_word else None,
            errors=errors,
        )

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    @property
    def state(self) -> VoiceState:
        return self._state

    @property
    def wake_word_state(self) -> WakeWordState:
        return self._wake_word_state


# Global instance
_voice_manager: Optional[VoiceManager] = None


def get_voice_manager(config: VoiceManagerConfig = None) -> VoiceManager:
    """Get or create global VoiceManager instance."""
    global _voice_manager
    if _voice_manager is None:
        _voice_manager = VoiceManager(config)
    return _voice_manager