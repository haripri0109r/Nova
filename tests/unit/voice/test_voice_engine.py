"""
Unit tests for Voice Engine.
"""
import pytest
from unittest.mock import AsyncMock, Mock, patch, MagicMock
import asyncio

# Mock heavy dependencies
import sys
sys.modules['pyaudio'] = MagicMock()
sys.modules['soundfile'] = MagicMock()
sys.modules['vosk'] = MagicMock()
sys.modules['whisper'] = MagicMock()
sys.modules['faster_whisper'] = MagicMock()
sys.modules['piper'] = MagicMock()
sys.modules['elevenlabs'] = MagicMock()
sys.modules['win32com'] = MagicMock()
sys.modules['comtypes'] = MagicMock()
sys.modules['TTS'] = MagicMock()

import pytest
from src.nova.voice import (
    VoiceEngine,
    VoiceManager,
    AudioManager,
    STTProvider,
    TTSProvider,
    WakeWordDetector,
    VoiceEngineConfig,
    VoiceManagerConfig,
    AudioConfig,
    STTConfig,
    TTSConfig,
    WakeWordConfig,
    SpeechResult,
    VoiceRequest,
    VoiceResponse,
    WakeWordResult,
    VoiceEngineHealth,
    VoiceState,
    WakeWordState,
    STTProvider as STTProviderEnum,
    TTSProvider as TTSProviderEnum,
    WakeWordEngine,
    BaseSTTProvider,
    BaseTTSProvider,
    BaseWakeWordProvider,
    PlaceholderSTTProvider,
    PlaceholderTTSProvider,
    PlaceholderWakeWordProvider,
    create_stt_provider,
    create_tts_provider,
    create_wakeword_provider,
    get_available_stt_providers,
    get_available_tts_providers,
    get_available_wakeword_engines,
)


class TestVoiceEngineConfig:
    """Tests for VoiceEngineConfig."""

    def test_default_config(self):
        config = VoiceEngineConfig()
        assert config.auto_initialize is True
        assert isinstance(config.audio_config, AudioConfig)
        assert isinstance(config.stt_config, STTConfig)
        assert isinstance(config.tts_config, TTSConfig)
        assert isinstance(config.wake_word_config, WakeWordConfig)

    def test_custom_config(self):
        audio_cfg = AudioConfig(sample_rate=44100)
        stt_cfg = STTConfig(provider=STTProviderEnum.PLACEHOLDER)
        config = VoiceEngineConfig(
            audio_config=audio_cfg,
            stt_config=stt_cfg,
            auto_initialize=False,
        )
        assert config.audio_config.sample_rate == 44100
        assert config.stt_config.provider == STTProviderEnum.PLACEHOLDER
        assert config.auto_initialize is False


class TestSTTProviders:
    """Tests for STT provider factory and placeholder."""

    def test_get_available_stt_providers(self):
        providers = get_available_stt_providers()
        assert STTProviderEnum.PLACEHOLDER in providers
        assert STTProviderEnum.VOSK in providers
        assert STTProviderEnum.WHISPER in providers

    def test_create_placeholder_stt_provider(self):
        config = STTConfig(provider=STTProviderEnum.PLACEHOLDER)
        provider = create_stt_provider(config)
        assert isinstance(provider, PlaceholderSTTProvider)

    @pytest.mark.asyncio
    async def test_placeholder_stt_transcribe(self):
        config = STTConfig(provider=STTProviderEnum.PLACEHOLDER)
        provider = create_stt_provider(config)
        await provider.initialize()
        
        result = await provider.transcribe(b"fake audio")
        assert isinstance(result, SpeechResult)
        assert result.text == "[placeholder] transcribed text"
        assert result.confidence == 1.0
        assert result.provider == "placeholder"

    @pytest.mark.asyncio
    async def test_placeholder_stt_cleanup(self):
        config = STTConfig(provider=STTProviderEnum.PLACEHOLDER)
        provider = create_stt_provider(config)
        await provider.initialize()
        await provider.cleanup()
        assert provider.is_initialized is False


class TestTTSProviders:
    """Tests for TTS provider factory and placeholder."""

    def test_get_available_tts_providers(self):
        providers = get_available_tts_providers()
        assert TTSProviderEnum.PLACEHOLDER in providers
        assert TTSProviderEnum.PIPER in providers
        assert TTSProviderEnum.ELEVENLABS in providers

    def test_create_placeholder_tts_provider(self):
        config = TTSConfig(provider=TTSProviderEnum.PLACEHOLDER)
        provider = create_tts_provider(config)
        assert isinstance(provider, PlaceholderTTSProvider)

    @pytest.mark.asyncio
    async def test_placeholder_tts_synthesize(self):
        config = TTSConfig(provider=TTSProviderEnum.PLACEHOLDER)
        provider = create_tts_provider(config)
        await provider.initialize()
        
        request = VoiceRequest(text="Hello world")
        result = await provider.synthesize(request)
        assert isinstance(result, VoiceResponse)
        assert len(result.audio_data) > 0
        assert result.provider == "placeholder"

    @pytest.mark.asyncio
    async def test_placeholder_tts_cleanup(self):
        config = TTSConfig(provider=TTSProviderEnum.PLACEHOLDER)
        provider = create_tts_provider(config)
        await provider.initialize()
        await provider.cleanup()
        assert provider.is_initialized is False


class TestWakeWordProviders:
    """Tests for wake-word provider factory and placeholder."""

    def test_get_available_wakeword_engines(self):
        engines = get_available_wakeword_engines()
        assert WakeWordEngine.PLACEHOLDER in engines
        assert WakeWordEngine.VOSK in engines
        assert WakeWordEngine.PRECISE in engines

    def test_create_placeholder_wakeword_provider(self):
        config = WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER)
        provider = create_wakeword_provider(config)
        assert isinstance(provider, PlaceholderWakeWordProvider)

    @pytest.mark.asyncio
    async def test_placeholder_wakeword_process(self):
        config = WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER)
        provider = create_wakeword_provider(config)
        await provider.initialize()
        
        result = await provider.process_audio(b"fake audio")
        assert isinstance(result, WakeWordResult)
        assert result.detected is False
        assert result.confidence == 0.0
        assert result.state == WakeWordState.DORMANT

    @pytest.mark.asyncio
    async def test_placeholder_wakeword_listening(self):
        config = WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER)
        provider = create_wakeword_provider(config)
        await provider.initialize()
        
        await provider.start_listening()
        assert provider.is_listening is True
        
        await provider.stop_listening()
        assert provider.is_listening is False

    @pytest.mark.asyncio
    async def test_placeholder_wakeword_cleanup(self):
        config = WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER)
        provider = create_wakeword_provider(config)
        await provider.initialize()
        await provider.cleanup()
        assert provider.is_initialized is False


class TestVoiceManager:
    """Tests for VoiceManager initialization and operations."""

    @pytest.fixture
    def manager_config(self):
        return VoiceManagerConfig(
            audio_config=AudioConfig(),
            stt_config=STTConfig(provider=STTProviderEnum.PLACEHOLDER),
            tts_config=TTSConfig(provider=TTSProviderEnum.PLACEHOLDER),
            wake_word_config=WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER),
        )

    @pytest.mark.asyncio
    async def test_initialize(self, manager_config):
        manager = VoiceManager(manager_config)
        await manager.initialize()
        
        assert manager.is_initialized is True
        assert manager.state == VoiceState.IDLE
        assert manager.wake_word_state == WakeWordState.DORMANT
        
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_speak_text(self, manager_config):
        manager = VoiceManager(manager_config)
        await manager.initialize()
        
        result = await manager.speak_text("Hello world")
        assert isinstance(result, VoiceResponse)
        assert len(result.audio_data) > 0
        
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_transcribe(self, manager_config):
        manager = VoiceManager(manager_config)
        await manager.initialize()
        
        result = await manager.transcribe(b"fake audio")
        assert isinstance(result, SpeechResult)
        assert result.text == "[placeholder] transcribed text"
        
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_wake_word_detection(self, manager_config):
        manager = VoiceManager(manager_config)
        await manager.initialize()
        
        await manager.start_wake_word_detection()
        assert manager.wake_word_state == WakeWordState.ACTIVE
        
        result = await manager.process_wake_word(b"fake audio")
        assert isinstance(result, WakeWordResult)
        assert result.detected is False
        
        await manager.stop_wake_word_detection()
        assert manager.wake_word_state == WakeWordState.DORMANT
        
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_health_check(self, manager_config):
        manager = VoiceManager(manager_config)
        await manager.initialize()
        
        # Mock the audio device list for health check
        from src.nova.voice.models import AudioDevice
        manager._audio.list_devices = Mock(return_value=[
            AudioDevice(
                index=0,
                name="Mock Input Device",
                max_input_channels=1,
                max_output_channels=0,
                default_sample_rate=16000,
                is_default_input=True,
                is_default_output=False,
            )
        ])
        
        health = await manager.health_check()
        assert isinstance(health, VoiceEngineHealth)
        assert health.status == "healthy"
        assert health.state == VoiceState.IDLE
        
        await manager.cleanup()

    @pytest.mark.asyncio
    async def test_event_callbacks(self, manager_config):
        manager = VoiceManager(manager_config)
        await manager.initialize()
        
        callback_results = []
        
        def on_speech(result):
            callback_results.append(("speech", result))
        
        def on_wake_word(result):
            callback_results.append(("wake_word", result))
        
        def on_state_change(data):
            callback_results.append(("state_change", data))
        
        manager.on("on_speech", on_speech)
        manager.on("on_wake_word", on_wake_word)
        manager.on("on_state_change", on_state_change)
        
        await manager.speak_text("Test")
        
        # Check that callbacks were called
        assert len(callback_results) > 0
        
        await manager.cleanup()


class TestVoiceEngine:
    """Tests for VoiceEngine high-level API."""

    @pytest.mark.asyncio
    async def test_initialize(self):
        config = VoiceEngineConfig(
            audio_config=AudioConfig(),
            stt_config=STTConfig(provider=STTProviderEnum.PLACEHOLDER),
            tts_config=TTSConfig(provider=TTSProviderEnum.PLACEHOLDER),
            wake_word_config=WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER),
        )
        engine = VoiceEngine(config)
        await engine.initialize()
        
        assert engine.is_initialized is True
        
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_speak_text(self):
        config = VoiceEngineConfig(
            audio_config=AudioConfig(),
            stt_config=STTConfig(provider=STTProviderEnum.PLACEHOLDER),
            tts_config=TTSConfig(provider=TTSProviderEnum.PLACEHOLDER),
            wake_word_config=WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER),
        )
        engine = VoiceEngine(config)
        await engine.initialize()
        
        result = await engine.speak_text("Hello world")
        assert isinstance(result, VoiceResponse)
        
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_transcribe(self):
        config = VoiceEngineConfig(
            audio_config=AudioConfig(),
            stt_config=STTConfig(provider=STTProviderEnum.PLACEHOLDER),
            tts_config=TTSConfig(provider=TTSProviderEnum.PLACEHOLDER),
            wake_word_config=WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER),
        )
        engine = VoiceEngine(config)
        await engine.initialize()
        
        result = await engine.transcribe(b"fake audio")
        assert isinstance(result, SpeechResult)
        
        await engine.cleanup()

    @pytest.mark.asyncio
    async def test_wake_word(self):
        config = VoiceEngineConfig(
            audio_config=AudioConfig(),
            stt_config=STTConfig(provider=STTProviderEnum.PLACEHOLDER),
            tts_config=TTSConfig(provider=TTSProviderEnum.PLACEHOLDER),
            wake_word_config=WakeWordConfig(engine=WakeWordEngine.PLACEHOLDER),
        )
        engine = VoiceEngine(config)
        await engine.initialize()
        
        await engine.start_wake_word_detection()
        assert engine.wake_word_state == WakeWordState.ACTIVE
        
        result = await engine.process_wake_word(b"fake audio")
        assert isinstance(result, WakeWordResult)
        
        await engine.stop_wake_word_detection()
        assert engine.wake_word_state == WakeWordState.DORMANT
        
        await engine.cleanup()


class TestAudioConfig:
    """Tests for AudioConfig."""

    def test_default_audio_config(self):
        config = AudioConfig()
        assert config.sample_rate == 16000
        assert config.channels == 1
        assert config.chunk_size == 1024

    def test_custom_audio_config(self):
        config = AudioConfig(sample_rate=44100, channels=2, chunk_size=2048)
        assert config.sample_rate == 44100
        assert config.channels == 2
        assert config.chunk_size == 2048


class TestModels:
    """Tests for data models."""

    def test_speech_result(self):
        result = SpeechResult(text="Hello", confidence=0.9)
        assert result.text == "Hello"
        assert result.confidence == 0.9

    def test_voice_request(self):
        request = VoiceRequest(text="Hello", voice="test", speed=1.5)
        assert request.text == "Hello"
        assert request.voice == "test"
        assert request.speed == 1.5

    def test_voice_response(self):
        response = VoiceResponse(audio_data=b"audio", duration_ms=1000)
        assert response.audio_data == b"audio"
        assert response.duration_ms == 1000

    def test_wake_word_result(self):
        result = WakeWordResult(detected=True, keyword="hey nova", confidence=0.95)
        assert result.detected is True
        assert result.keyword == "hey nova"
        assert result.confidence == 0.95


if __name__ == "__main__":
    pytest.main([__file__, "-v"])