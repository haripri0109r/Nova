"""
Voice Engine type definitions.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class STTProvider(str, Enum):
    VOSK = "vosk"
    WHISPER = "whisper"
    WHISPER_CPP = "whisper_cpp"
    FASTER_WHISPER = "faster_whisper"
    PLACEHOLDER = "placeholder"


class TTSProvider(str, Enum):
    PIPER = "piper"
    ELEVENLABS = "elevenlabs"
    WINDOWS_SAPI = "windows_sapi"
    COQUI = "coqui"
    PLACEHOLDER = "placeholder"


class WakeWordEngine(str, Enum):
    VOSK = "vosk"
    PRECISE = "precise"
    OPEN_WAKEWORD = "openwakeword"
    PLACEHOLDER = "placeholder"


class AudioFormat(str, Enum):
    WAV = "wav"
    MP3 = "mp3"
    OGG = "ogg"
    PCM = "pcm"


class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    ERROR = "error"


class WakeWordState(str, Enum):
    DORMANT = "dormant"
    ACTIVE = "active"
    DETECTED = "detected"


class AudioConfig(BaseModel):
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    format: AudioFormat = AudioFormat.PCM
    device_index: Optional[int] = None


class STTConfig(BaseModel):
    provider: STTProvider = STTProvider.FASTER_WHISPER
    model_path: Optional[str] = None
    language: str = "en"
    sensitivity: float = 0.5
    extra: Dict[str, Any] = Field(default_factory=dict)


class TTSConfig(BaseModel):
    provider: TTSProvider = TTSProvider.WINDOWS_SAPI
    voice: Optional[str] = None
    speed: float = 1.0
    pitch: float = 1.0
    volume: float = 1.0
    extra: Dict[str, Any] = Field(default_factory=dict)


class WakeWordConfig(BaseModel):
    engine: WakeWordEngine = WakeWordEngine.PLACEHOLDER
    model_path: Optional[str] = None
    sensitivity: float = 0.5
    keywords: List[str] = Field(default_factory=lambda: ["hey nova", "hello nova"])
    extra: Dict[str, Any] = Field(default_factory=dict)


class VoiceEngineConfig(BaseModel):
    audio_config: AudioConfig = Field(default_factory=AudioConfig)
    stt_config: STTConfig = Field(default_factory=STTConfig)
    tts_config: TTSConfig = Field(default_factory=TTSConfig)
    wake_word_config: WakeWordConfig = Field(default_factory=WakeWordConfig)
    auto_initialize: bool = True