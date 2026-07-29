"""
Nova Voice Engine Package.

A comprehensive voice engine for speech recognition, synthesis, wake-word detection,
and audio I/O with support for multiple providers.
"""
from .engine import VoiceEngine, get_voice_engine
from .manager import VoiceManager, get_voice_manager, VoiceManagerConfig
from .audio import AudioManager, get_audio_manager
from .stt import STTService, get_stt_provider, BaseSTTProvider
from .tts import TTSService, get_tts_provider, BaseTTSProvider
from .wake_word import WakeWordDetector, get_wake_word_detector, BaseWakeWordProvider
from .providers import (
    BaseSTTProvider,
    BaseTTSProvider,
    BaseWakeWordProvider,
    PlaceholderSTTProvider,
    PlaceholderTTSProvider,
    PlaceholderWakeWordProvider,
    register_stt_provider,
    register_tts_provider,
    register_wakeword_provider,
    create_stt_provider,
    create_tts_provider,
    create_wakeword_provider,
    get_available_stt_providers,
    get_available_tts_providers,
    get_available_wakeword_engines,
)
from .models import (
    AudioDevice,
    SpeechResult,
    VoiceRequest,
    VoiceResponse,
    WakeWordResult,
    VoiceEngineHealth,
)
from .types import (
    STTProvider,
    TTSProvider,
    WakeWordEngine,
    AudioFormat,
    VoiceState,
    WakeWordState,
    AudioConfig,
    STTConfig,
    TTSConfig,
    WakeWordConfig,
    VoiceEngineConfig,
)
from .exceptions import (
    VoiceEngineError,
    AudioDeviceError,
    STTError,
    TTSError,
    WakeWordError,
    ProviderError,
    AudioPipelineError,
)

__all__ = [
    # Engine & Manager
    "VoiceEngine",
    "get_voice_engine",
    "VoiceManager",
    "get_voice_manager",
    "VoiceManagerConfig",
    # Audio
    "AudioManager",
    "get_audio_manager",
    # STT
    "STTService",
    "get_stt_provider",
    "BaseSTTProvider",
    # TTS
    "TTSService",
    "get_tts_provider",
    "BaseTTSProvider",
    # Wake Word
    "WakeWordDetector",
    "get_wake_word_detector",
    "BaseWakeWordProvider",
    # Providers
    "PlaceholderSTTProvider",
    "PlaceholderTTSProvider",
    "PlaceholderWakeWordProvider",
    "register_stt_provider",
    "register_tts_provider",
    "register_wakeword_provider",
    "create_stt_provider",
    "create_tts_provider",
    "create_wakeword_provider",
    "get_available_stt_providers",
    "get_available_tts_providers",
    "get_available_wakeword_engines",
    # Models
    "AudioDevice",
    "SpeechResult",
    "VoiceRequest",
    "VoiceResponse",
    "WakeWordResult",
    "VoiceEngineHealth",
    # Types
    "STTProvider",
    "TTSProvider",
    "WakeWordEngine",
    "AudioFormat",
    "VoiceState",
    "WakeWordState",
    "AudioConfig",
    "STTConfig",
    "TTSConfig",
    "WakeWordConfig",
    "VoiceEngineConfig",
    # Exceptions
    "VoiceEngineError",
    "AudioDeviceError",
    "STTError",
    "TTSError",
    "WakeWordError",
    "ProviderError",
    "AudioPipelineError",
]