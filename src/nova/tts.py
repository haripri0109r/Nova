#!/usr/bin/env python3
"""
Local Windows Text-to-Speech (TTS) using Windows SAPI.
Provides synchronous, local, and thread-safe speech synthesis without cloud credentials or internet access.
"""

from __future__ import annotations

import logging
from typing import Optional

from .config import settings
from .voice.tts import WindowsSAPIProvider, BaseTTSProvider
from .voice.types import TTSConfig, TTSProvider

log = logging.getLogger("nova.tts")

_active_provider: Optional[BaseTTSProvider] = None


def get_tts_provider() -> BaseTTSProvider:
    """Get the active TTS provider instance (defaults to WindowsSAPIProvider)."""
    global _active_provider
    if _active_provider is None:
        config = TTSConfig(
            provider=TTSProvider.WINDOWS_SAPI,
            voice=getattr(settings, "tts_voice", None),
            speed=getattr(settings, "tts_speed", 1.0),
            volume=getattr(settings, "tts_volume", 1.0),
        )
        _active_provider = WindowsSAPIProvider(config)
    return _active_provider


def set_tts_provider(provider: Optional[BaseTTSProvider]) -> None:
    """Set or reset the active TTS provider (useful for testing or custom providers)."""
    global _active_provider
    _active_provider = provider


def say(text: str) -> None:
    """Speak text using the active local TTS provider (Windows SAPI)."""
    if not text or not text.strip():
        return
    try:
        provider = get_tts_provider()
        if hasattr(provider, "speak"):
            provider.speak(text)
        else:
            log.warning("Active TTS provider does not support direct speak()")
    except Exception as e:
        log.warning("Local TTS failed: %s", e)


def say_nova_welcome() -> None:
    """Speak the Nova welcome phrase using the active local TTS provider."""
    if not settings.nova_welcome_enabled or not settings.nova_welcome_phrase.strip():
        return
    text = settings.nova_welcome_phrase.strip()
    say(text)