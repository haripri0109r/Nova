"""
Audio device management and I/O for voice operations.
"""
from __future__ import annotations

import logging
import asyncio
from typing import Optional, List, Dict, Any, AsyncIterator
from dataclasses import dataclass
from contextlib import asynccontextmanager

import numpy as np

from .types import AudioConfig, AudioFormat
from .models import AudioDevice
from .exceptions import AudioDeviceError

logger = logging.getLogger("nova.voice.audio")


@dataclass
class AudioStreamConfig:
    """Configuration for audio stream."""
    sample_rate: int = 16000
    channels: int = 1
    chunk_size: int = 1024
    format: AudioFormat = AudioFormat.PCM
    device_index: Optional[int] = None


class AudioManager:
    """
    Manages audio input/output devices and streams.

    Responsibilities:
    - Device enumeration
    - Audio recording/playback
    - Stream management
    - Device configuration
    """

    def __init__(self, config: Optional[AudioConfig] = None):
        self.config = config or AudioConfig()
        self._input_stream = None
        self._output_stream = None
        self._pyaudio = None
        self._initialized = False

    async def initialize(self) -> bool:
        """Initialize audio system."""
        try:
            import pyaudio
            self._pyaudio = pyaudio.PyAudio()
            self._initialized = True
            logger.info("Audio manager initialized")
            return True
        except ImportError:
            logger.warning("pyaudio not installed")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize audio: {e}")
            return False

    async def cleanup(self) -> None:
        """Clean up audio resources."""
        await self.stop_recording()
        await self.stop_playback()
        if self._pyaudio:
            self._pyaudio.terminate()
        self._initialized = False

    def list_devices(self) -> List[AudioDevice]:
        """List all available audio devices."""
        if not self._pyaudio:
            return []

        devices = []
        for i in range(self._pyaudio.get_device_count()):
            info = self._pyaudio.get_device_info_by_index(i)
            devices.append(AudioDevice(
                index=i,
                name=info["name"],
                max_input_channels=int(info["maxInputChannels"]),
                max_output_channels=int(info["maxOutputChannels"]),
                default_sample_rate=int(info["defaultSampleRate"]),
                is_default_input=(i == self._pyaudio.get_default_input_device_info()["index"]),
                is_default_output=(i == self._pyaudio.get_default_output_device_info()["index"]),
            ))
        return devices

    def get_default_input_device(self) -> Optional[AudioDevice]:
        """Get default input device."""
        devices = self.list_devices()
        for d in devices:
            if d.is_default_input:
                return d
        return devices[0] if devices else None

    def get_default_output_device(self) -> Optional[AudioDevice]:
        """Get default output device."""
        devices = self.list_devices()
        for d in devices:
            if d.is_default_output:
                return d
        return devices[0] if devices else None

    @asynccontextmanager
    async def record_stream(
        self,
        stream_config: AudioStreamConfig = None,
    ) -> AsyncIterator[AsyncIterator[bytes]]:
        """
        Context manager for recording audio stream.

        Usage:
            async with audio_manager.record_stream() as stream:
                async for chunk in stream:
                    process(chunk)
        """
        if not self._initialized:
            await self.initialize()

        import pyaudio

        config = stream_config or AudioStreamConfig(
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            chunk_size=self.config.chunk_samples(),
            format=self.config.format,
            device_index=self.config.device_index,
        )

        stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=config.channels,
            rate=config.sample_rate,
            input=True,
            input_device_index=config.device_index,
            frames_per_buffer=config.chunk_size,
        )

        async def audio_generator():
            try:
                while True:
                    data = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: stream.read(config.chunk_size, exception_on_overflow=False)
                    )
                    yield data
            except asyncio.CancelledError:
                pass
            finally:
                stream.stop_stream()
                stream.close()

        try:
            yield audio_generator()
        finally:
            pass  # Cleanup handled in generator

    async def record(
        self,
        duration: float,
        stream_config: AudioStreamConfig = None,
    ) -> bytes:
        """Record audio for specified duration."""
        config = stream_config or AudioStreamConfig(
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            chunk_size=self.config.chunk_samples(),
        )

        frames = []
        async for chunk in self.record_stream(config):
            frames.append(chunk)
            # Check duration
            total_samples = sum(len(f) // 2 for f in frames)  # 16-bit = 2 bytes per sample
            if total_samples / config.sample_rate >= duration:
                break

        return b"".join(frames)

    @asynccontextmanager
    async def playback_stream(
        self,
        stream_config: AudioStreamConfig = None,
    ) -> AsyncIterator[Callable[[bytes], None]]:
        """
        Context manager for audio playback.

        Usage:
            async with audio_manager.playback_stream() as play:
                await play(audio_chunk)
        """
        if not self._initialized:
            await self.initialize()

        import pyaudio

        config = stream_config or AudioStreamConfig(
            sample_rate=self.config.sample_rate,
            channels=self.config.channels,
            format=AudioFormat.PCM,
            device_index=self.config.device_index,
        )

        stream = self._pyaudio.open(
            format=pyaudio.paInt16,
            channels=config.channels,
            rate=config.sample_rate,
            output=True,
            output_device_index=config.device_index,
            frames_per_buffer=config.chunk_size,
        )

        async def write_audio(data: bytes):
            await asyncio.get_event_loop().run_in_executor(
                None,
                stream.write,
                data
            )

        try:
            yield write_audio
        finally:
            stream.stop_stream()
            stream.close()

    async def play(self, audio_data: bytes, sample_rate: int = 16000) -> None:
        """Play audio data."""
        async with self.playback_stream(AudioStreamConfig(sample_rate=sample_rate)) as play:
            await play(audio_data)

    async def play_file(self, file_path: Path) -> None:
        """Play audio file."""
        import soundfile as sf

        data, sample_rate = sf.read(file_path)
        audio_data = (data * 32767).astype(np.int16).tobytes()
        await self.play(audio_data, sample_rate)

    async def stop_recording(self) -> None:
        """Stop any active recording."""
        pass  # Handled by context managers

    async def stop_playback(self) -> None:
        """Stop any active playback."""
        pass  # Handled by context managers

    def get_input_level(self) -> float:
        """Get current input audio level (0.0 to 1.0)."""
        # This would require active recording stream
        return 0.0

    def set_input_volume(self, volume: float) -> None:
        """Set input volume (0.0 to 1.0)."""
        # Platform-specific implementation needed
        pass

    def set_output_volume(self, volume: float) -> None:
        """Set output volume (0.0 to 1.0)."""
        # Platform-specific implementation needed
        pass


# Global instance
_audio_manager: Optional[AudioManager] = None


def get_audio_manager(config: Optional[AudioConfig] = None) -> AudioManager:
    """Get or create global audio manager instance."""
    global _audio_manager
    if _audio_manager is None:
        _audio_manager = AudioManager(config)
    return _audio_manager