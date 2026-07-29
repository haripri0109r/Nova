"""
Voice Engine Exceptions
"""
from typing import Optional, Dict, Any


class VoiceEngineError(Exception):
    """Base exception for voice engine errors."""

    def __init__(self, message: str, code: str = "VOICE_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error": self.message,
            "code": self.code,
            "details": self.details,
        }


class AudioDeviceError(VoiceEngineError):
    def __init__(self, message: str, device: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="AUDIO_DEVICE_ERROR",
            details={"device": device, **(details or {})},
        )


class STTError(VoiceEngineError):
    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="STT_ERROR",
            details={"provider": provider, **(details or {})},
        )


class TTSError(VoiceEngineError):
    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="TTS_ERROR",
            details={"provider": provider, **(details or {})},
        )


class WakeWordError(VoiceEngineError):
    def __init__(self, message: str, engine: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="WAKE_WORD_ERROR",
            details={"engine": engine, **(details or {})},
        )


class ProviderError(VoiceEngineError):
    def __init__(self, message: str, provider: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="PROVIDER_ERROR",
            details={"provider": provider, **(details or {})},
        )


class AudioPipelineError(VoiceEngineError):
    def __init__(self, message: str, stage: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            code="PIPELINE_ERROR",
            details={"stage": stage, **(details or {})},
        )