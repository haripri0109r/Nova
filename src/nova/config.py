#!/usr/bin/env python3
"""
Configuration for Nova using Pydantic BaseSettings.
All runtime constants are defined as typed fields with validation.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, validator, root_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_vosk_model_path() -> Path:
    # repo root is three levels up from this file (src/nova/config.py)
    return Path(__file__).resolve().parent.parent.parent / "models" / "vosk-model-en-us-0.22-lgraph"


def _default_cache_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / ".cache" / "nova_welcome"


class Settings(BaseSettings):
    # pydantic-settings v2 uses model_config
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parent.parent.parent / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Audio ---------------------------------------------------------
    sample_rate: int = Field(default=44100, gt=0)
    block_ms: int = Field(default=40, gt=0)
    channels: int = Field(default=1, ge=1, le=2)

    input_probe_s: float = Field(default=0.5, gt=0)
    input_silent_rms: float = Field(default=0.001, ge=0)

    # --- VAD / Wake phrase ---------------------------------------------
    vad_sample_rate: int = Field(default=16000, gt=0)
    vad_frame_size: int = Field(default=512, gt=0)
    vad_silence_ms: int = Field(default=500, ge=0)
    vad_max_utterance_s: int = Field(default=30, gt=0)
    vad_threshold: float = Field(default=0.5, ge=0.0, le=1.0)

    # --- Whisper --------------------------------------------------------
    whisper_model: str = Field(default="base")

    # --- Vosk ----------------------------------------------------------
    vosk_model_path: Path = Field(default_factory=_default_vosk_model_path)

    # --- LLM Providers -------------------------------------------------
    llm_use_ollama: bool = Field(default=True)
    llm_ollama_model: str = Field(default="qwen3:8b")
    llm_ollama_base_url: str = Field(default="http://localhost:11434")

    llm_use_openrouter: bool = Field(default=True)
    llm_openrouter_model: str = Field(default="qwen/qwen3-coder")
    llm_openrouter_api_key: Optional[str] = Field(
        default=None,
        validation_alias="OPENROUTER_API_KEY",
    )

    llm_use_gemini: bool = Field(default=True)
    llm_gemini_model: str = Field(default="gemini-2.0-flash")
    llm_gemini_api_key: Optional[str] = Field(
        default=None,
        validation_alias="GEMINI_API_KEY",
    )

    # LLM Provider mode: True=dev (Ollama optional), False=prod (OpenRouter->Gemini)
    llm_dev_mode: bool = Field(default=True, validation_alias="NOVA_LLM_DEV_MODE")

    # --- Logging -------------------------------------------------------
    nova_log_level: str = Field(default="INFO")

    # --- Spotify / media -----------------------------------------------
    song_uri: str = Field(
        default="https://open.spotify.com/track/39shmbIHICJ2Wxnk1fPSdz?si=2900c75c2e2d4b82"
    )

    # --- Cursor ---------------------------------------------------------
    focus_existing_cursor_on_wake: bool = True
    open_new_cursor_on_wake: bool = False
    cursor_open_fullscreen: bool = True

    # --- Chrome ---------------------------------------------------------
    open_claude_code_in_chrome: bool = True
    open_binance_btc_in_chrome: bool = True
    open_chrome_fullscreen: bool = True
    chrome_separate_site_profiles: bool = False
    claude_chrome_monitor: int = Field(default=1, ge=1)
    binance_chrome_monitor: int = Field(default=3, ge=1)

    # --- Welcome / TTS --------------------------------------------------
    nova_welcome_enabled: bool = True
    nova_welcome_phrase: str = (
        "Welcome home sir. "
        "Congratulations on the new client for your SaaS app—make sure to follow up. "
        "If it helps: a short, specific note while the deal is still fresh usually "
        "anchors trust better than a polished deck sent cold a few days later."
    )
    nova_after_song_delay_s: float = Field(default=1.0, ge=0)
    nova_welcome_cache_enabled: bool = True

    # ElevenLabs ---------------------------------------------------------
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_voice_id: Optional[str] = None
    elevenlabs_model_id: str = "eleven_multilingual_v2"
    elevenlabs_output_format: str = "pcm_24000"
    elevenlabs_pcm_sample_rate: Optional[int] = None

    # Chrome URLs --------------------------------------------------------
    claude_code_url: str = "https://claude.ai/new"
    binance_btc_url: str = "https://www.binance.com/en/trade/BTC_USDT"

    # Chrome window sizing -----------------------------------------------
    chrome_window_width: int = Field(default=1400, ge=400)
    chrome_window_height: int = Field(default=900, ge=300)
    chrome_new_window_wait_s: float = Field(default=25.0, ge=3.0)

    # Brightness step for voice commands -----------------------------------
    nova_brightness_step: int = Field(default=10, ge=1, le=100)

    # Cache dir ----------------------------------------------------------
    nova_welcome_cache_dir: Optional[Path] = None

    # Audio input device -------------------------------------------------
    nova_input_device: Optional[str] = None

    # --------------------------------------------------------------------
    # Validators
    # --------------------------------------------------------------------
    @validator("nova_log_level")
    def _valid_log_level(cls, v: str) -> str:
        lvl = v.upper()
        if lvl not in logging._nameToLevel:
            raise ValueError(f"Invalid log level: {v}")
        return lvl

    @validator("vosk_model_path")
    def _vosk_model_exists(cls, v: Path) -> Path:
        if not v.is_dir():
            raise FileNotFoundError(
                f"Vosk model not found at {v}. "
                "Run `python scripts/download_vosk_model.py` to fetch it."
            )
        return v

    @root_validator(skip_on_failure=True)
    def _warn_missing_elevenlabs(cls, values):
        if values.get("nova_welcome_enabled") and not values.get("elevenlabs_voice_id"):
            logging.getLogger(__name__).warning(
                "NOVA_WELCOME_ENABLED=True but ELEVENLABS_VOICE_ID is not set. "
                "TTS will be skipped until both ELEVENLABS_VOICE_ID and ELEVENLABS_API_KEY are provided."
            )
        return values


# Single instance used throughout the project
settings = Settings()


# --------------------------------------------------------------------
# Back‑compatibility helpers used by other modules
# --------------------------------------------------------------------
def elevenlabs_env_config() -> tuple[str, str, str, int]:
    """Return (voice_id, model_id, output_format, pcm_sample_rate)."""
    voice = settings.elevenlabs_voice_id or ""
    model = settings.elevenlabs_model_id
    fmt = settings.elevenlabs_output_format
    rate = settings.elevenlabs_pcm_sample_rate or 24000
    return voice, model, fmt, rate


def _nova_welcome_cache_dir() -> Path:
    base = Path(__file__).resolve().parent.parent.parent
    override = settings.nova_welcome_cache_dir
    if override:
        return Path(override).expanduser().resolve()
    return base / ".cache" / "nova_welcome"


def _nova_welcome_cache_path(
    text: str, voice_id: str, model_id: str, output_format: str
) -> Path:
    import hashlib

    key = f"{text}|{voice_id}|{model_id}|{output_format}".encode()
    digest = hashlib.sha256(key).hexdigest()[:24]
    return _nova_welcome_cache_dir() / f"{digest}.wav"


def _chrome_window_size() -> tuple[int, int]:
    return (settings.chrome_window_width, settings.chrome_window_height)


def _chrome_site_user_data_dir(site_key: str) -> str:
    import tempfile
    from pathlib import Path

    p = Path(tempfile.gettempdir()) / "wake-trigger-chrome" / site_key
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _chrome_new_window_wait_timeout_s() -> float:
    return settings.chrome_new_window_wait_s