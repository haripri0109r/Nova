"""
Voice Engine data models.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from .types import VoiceState, WakeWordState, AudioFormat


class AudioDevice(BaseModel):
    """Audio input/output device information."""
    index: int
    name: str
    max_input_channels: int
    max_output_channels: int
    default_sample_rate: int
    is_default_input: bool = False
    is_default_output: bool = False


class SpeechResult(BaseModel):
    """Result from speech-to-text processing."""
    text: str
    confidence: float = Field(ge=0.0, le=1.0)
    language: str = "en"
    duration_ms: float = 0.0
    provider: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceRequest(BaseModel):
    """Request for text-to-speech synthesis."""
    text: str
    voice: Optional[str] = None
    speed: float = Field(default=1.0, gt=0.0)
    pitch: float = Field(default=1.0, gt=0.0)
    volume: float = Field(default=1.0, ge=0.0, le=1.0)
    format: AudioFormat = AudioFormat.WAV
    provider: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceResponse(BaseModel):
    """Response from text-to-speech synthesis."""
    audio_data: bytes
    format: AudioFormat = AudioFormat.WAV
    sample_rate: int = 16000
    duration_ms: float = 0.0
    provider: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WakeWordResult(BaseModel):
    """Result from wake-word detection."""
    detected: bool
    keyword: Optional[str] = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    state: WakeWordState = WakeWordState.DORMANT
    audio_buffer: Optional[bytes] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class VoiceEngineHealth(BaseModel):
    """Health status of the voice engine."""
    status: str
    state: VoiceState = VoiceState.IDLE
    wake_word_state: WakeWordState = WakeWordState.DORMANT
    audio_device: Optional[str] = None
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    wake_word_engine: Optional[str] = None
    last_check: datetime = Field(default_factory=datetime.utcnow)
    errors: List[str] = Field(default_factory=list)