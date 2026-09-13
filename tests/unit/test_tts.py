"""
Unit tests for Local Windows SAPI TTS integration (Phase 5.7B).
Verifies:
1. Default TTS provider is local Windows SAPI.
2. ElevenLabs is not instantiated by the active runtime.
3. No API key is required.
4. TTS abstraction works cleanly (say, say_nova_welcome, get_tts_provider, set_tts_provider).
5. Application can call TTS through the canonical interface.
6. TTS failure is handled safely without raising or crashing.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch, AsyncMock
import pytest

from nova.voice.types import TTSProvider, TTSConfig
from nova.voice.tts import WindowsSAPIProvider, BaseTTSProvider
from nova.tts import (
    get_tts_provider,
    set_tts_provider,
    say,
    say_nova_welcome,
)
from nova.config import settings


@pytest.fixture(autouse=True)
def reset_active_tts_provider():
    """Ensure active TTS provider is reset to default around each test."""
    set_tts_provider(None)
    yield
    set_tts_provider(None)


def test_default_tts_provider_is_windows_sapi():
    """Default active TTS provider must be WindowsSAPIProvider with WINDOWS_SAPI enum."""
    provider = get_tts_provider()
    assert isinstance(provider, WindowsSAPIProvider)
    assert provider.name == TTSProvider.WINDOWS_SAPI


def test_no_elevenlabs_instantiated_on_say():
    """Speaking text must NOT import, instantiate, or invoke ElevenLabs."""
    mock_elevenlabs = MagicMock()
    with patch.dict(sys.modules, {"elevenlabs": mock_elevenlabs, "elevenlabs.client": mock_elevenlabs}):
        with patch("win32com.client.Dispatch") as mock_dispatch:
            mock_speaker = MagicMock()
            mock_dispatch.return_value = mock_speaker

            say("Hello from Nova")

            # ElevenLabs must NEVER be called
            mock_elevenlabs.client.ElevenLabs.assert_not_called()
            # Windows SAPI must be called
            mock_dispatch.assert_called_with("SAPI.SpVoice")
            mock_speaker.Speak.assert_called_once_with("Hello from Nova")


def test_say_empty_or_whitespace_is_noop():
    """Empty or whitespace text should be an immediate no-op."""
    with patch("win32com.client.Dispatch") as mock_dispatch:
        say("")
        say("   ")
        say(None)
        mock_dispatch.assert_not_called()


def test_no_api_key_required_for_tts():
    """Windows SAPI TTS must function without any cloud API keys or credentials."""
    # Ensure all ElevenLabs keys are unset/None
    original_key = settings.elevenlabs_api_key
    original_voice = settings.elevenlabs_voice_id
    try:
        settings.elevenlabs_api_key = None
        settings.elevenlabs_voice_id = None

        with patch("win32com.client.Dispatch") as mock_dispatch:
            mock_speaker = MagicMock()
            mock_dispatch.return_value = mock_speaker

            say("Offline speech test")

            mock_speaker.Speak.assert_called_once_with("Offline speech test")
    finally:
        settings.elevenlabs_api_key = original_key
        settings.elevenlabs_voice_id = original_voice


def test_say_nova_welcome_calls_local_sapi():
    """Nova welcome message uses local Windows SAPI without ElevenLabs."""
    original_enabled = settings.nova_welcome_enabled
    original_phrase = settings.nova_welcome_phrase
    try:
        settings.nova_welcome_enabled = True
        settings.nova_welcome_phrase = "Welcome home commander."

        with patch("win32com.client.Dispatch") as mock_dispatch:
            mock_speaker = MagicMock()
            mock_dispatch.return_value = mock_speaker

            say_nova_welcome()

            mock_speaker.Speak.assert_called_once_with("Welcome home commander.")
    finally:
        settings.nova_welcome_enabled = original_enabled
        settings.nova_welcome_phrase = original_phrase


def test_tts_failure_is_handled_safely():
    """If SAPI raises an exception, say() must catch it and not crash caller."""
    with patch("win32com.client.Dispatch", side_effect=RuntimeError("SAPI hardware error")):
        # Must not raise
        say("This will fail silently in SAPI")


def test_custom_tts_provider_replacement():
    """The TTS abstraction allows setting a custom or mock provider."""
    class MockCustomTTS(BaseTTSProvider):
        def __init__(self):
            super().__init__(TTSConfig(provider=TTSProvider.PLACEHOLDER))
            self.spoken = []

        async def initialize(self) -> bool: return True
        async def cleanup(self) -> None: pass
        async def synthesize(self, request): pass
        async def synthesize_stream(self, request): pass
        async def synthesize_to_file(self, request, file_path): pass
        @property
        def name(self): return TTSProvider.PLACEHOLDER
        @property
        def capabilities(self): return None

        def speak(self, text: str) -> bool:
            self.spoken.append(text)
            return True

    mock_provider = MockCustomTTS()
    set_tts_provider(mock_provider)

    assert get_tts_provider() is mock_provider
    say("Custom provider test")
    assert mock_provider.spoken == ["Custom provider test"]


@pytest.mark.asyncio
async def test_application_can_call_tts_interface():
    """NovaApplication invocation path (asyncio.to_thread(say, ...)) functions correctly."""
    import asyncio

    with patch("win32com.client.Dispatch") as mock_dispatch:
        mock_speaker = MagicMock()
        mock_dispatch.return_value = mock_speaker

        # Replicate exact application call: await asyncio.to_thread(say, response_text)
        await asyncio.to_thread(say, "Done.")

        mock_speaker.Speak.assert_called_once_with("Done.")
