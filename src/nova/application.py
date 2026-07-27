"""
Nova Core Application - Main application lifecycle management.
"""
from __future__ import annotations

import asyncio
import logging
import signal
import sys
from typing import Any, Dict, Optional

from .config import settings
from .events import get_event_bus
from .brain import get_brain
from .wake_phrase import WakePhraseListener
from .tts import say_nova_welcome
from .audio_input import _choose_input_device, block_samples

log = logging.getLogger("nova.application")


class NovaApplication:
    """
    Main Nova application - manages the complete lifecycle:
    
    1. start()    - Initialize all components (audio, models, event bus, brain)
    2. run()      - Main loop: wake phrase → command → brain → response
    3. stop()     - Graceful shutdown of all components
    """
    
    def __init__(self) -> None:
        self._running = False
        self._stop_event = asyncio.Event()
        self._wake_listener: Optional[WakePhraseListener] = None
        self._brain = None
        self._event_bus = None
        self._welcome_sequence_done = False
        
        # Signal handlers for graceful shutdown
        self._setup_signal_handlers()
    
    def _setup_signal_handlers(self) -> None:
        """Register signal handlers for graceful shutdown."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self._signal_handler)
            except NotImplementedError:
                # Windows doesn't support add_signal_handler
                pass
    
    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        log.info("Shutdown signal received")
        self._stop_event.set()
    
    async def start(self) -> None:
        """Initialize all components."""
        if self._running:
            log.warning("Application already running")
            return
        
        log.info("Starting Nova application...")
        
        # 1. Initialize Event Bus
        self._event_bus = get_event_bus()
        await self._event_bus.start()
        log.info("Event bus started")
        
        # 2. Initialize Brain (which initializes Agent Orchestrator, Intent Engine, etc.)
        self._brain = get_brain()
        log.info("Brain initialized")
        
        # 3. Initialize Wake Phrase Listener (loads VAD + Whisper models)
        self._wake_listener = WakePhraseListener()
        log.info("Wake phrase listener initialized")
        
        # 4. Run welcome sequence
        await self._run_welcome_sequence()
        
        self._running = True
        log.info("Nova application started successfully")
    
    async def _run_welcome_sequence(self) -> None:
        """Run the welcome sequence: song → chrome → TTS → cursor."""
        if self._welcome_sequence_done:
            return
        
        log.info("Running welcome sequence...")
        
        try:
            # Play song
            if settings.song_uri.strip():
                from .automation.spotify import play_song
                play_song(settings.song_uri)
            
            # Open Chrome tabs
            if settings.open_claude_code_in_chrome:
                from .automation.chrome import open_claude_in_chrome
                open_claude_in_chrome()
            
            if settings.open_binance_btc_in_chrome:
                from .automation.chrome import open_binance_btc_in_chrome
                open_binance_btc_in_chrome()
            
            # TTS welcome
            if settings.nova_welcome_enabled and settings.nova_welcome_phrase.strip():
                delay = max(0.0, settings.nova_after_song_delay_s)
                if delay:
                    await asyncio.sleep(delay)
                # Run TTS in thread to not block
                await asyncio.to_thread(say_nova_welcome)
            
            # Open Cursor
            if settings.focus_existing_cursor_on_wake or settings.open_new_cursor_on_wake:
                from .automation.cursor_editor import open_cursor_window
                open_cursor_window()
            
            self._welcome_sequence_done = True
            log.info("Welcome sequence completed")
            
        except Exception as e:
            log.warning("Welcome sequence partially failed: %s", e)
    
    async def run(self) -> None:
        """
        Main application loop:
        1. Wait for wake phrase
        2. Listen for command
        3. Process through Brain
        4. Speak response via TTS
        """
        if not self._running:
            await self.start()
        
        log.info("Entering main loop - listening for 'hello nova'...")
        
        while self._running and not self._stop_event.is_set():
            try:
                # Phase 1: Wait for wake phrase (blocking, no timeout)
                text = await asyncio.to_thread(
                    self._wake_listener.listen_for_utterance
                )
                
                if text is None:
                    continue
                
                log.debug("Heard: %r", text)
                
                if not WakePhraseListener.matches_wake_phrase(text):
                    continue
                
                log.info("Wake phrase detected: %r — listening for command", text)
                
                # Phase 2a: Try to extract command from same utterance
                from .commands import extract_remainder, match_command
                remainder = extract_remainder(text)
                
                if remainder:
                    command_text = remainder
                    log.info("Command from same utterance: %r", remainder)
                else:
                    # Phase 2b: Listen for command
                    log.debug("Listening for command...")
                    command_text = await asyncio.to_thread(
                        self._wake_listener.listen_for_utterance,
                        stop_event=None,
                        timeout=12.0,
                        phrase_time_limit=12.0,
                    )
                    if command_text is None:
                        log.info("No command heard; returning to wake phrase detection")
                        continue
                    command_text = command_text
                    log.debug("Command heard: %r", command_text)
                
                # Phase 3: Process through Brain
                log.info("Processing command: %r", command_text)
                try:
                    result = await self._process_command(command_text)
                    log.info("Command processed: %s", result.get("status", "unknown"))
                except Exception as e:
                    log.error("Command processing failed: %s", e)
                
            except Exception as e:
                log.error("Main loop error: %s", e)
                await asyncio.sleep(1)  # Prevent tight loop on error
    
    async def _process_command(self, command_text: str) -> Dict[str, Any]:
        """Process a command through the Brain pipeline."""
        from .events.events import UserCommandReceivedEvent, GoalCompletedEvent, GoalFailedEvent
        
        # Emit user command event
        self._event_bus.publish(
            UserCommandReceivedEvent(
                source="application",
                payload={"text": command_text}
            )
        )
        
        # Process through Brain (which uses Agent Orchestrator)
        result = await asyncio.to_thread(self._brain.process, command_text)
        
        # Emit completion event
        if result.get("status") == "completed":
            self._event_bus.publish(
                GoalCompletedEvent(
                    source="application",
                    payload={"summary": str(result.get("result", ""))}
                )
            )
        else:
            self._event_bus.publish(
                GoalFailedEvent(
                    source="application",
                    payload={"reason": result.get("message", "Unknown error")}
                )
            )
        
        # Speak response if there's a summary
        summary = result.get("summary") or result.get("result", {}).get("detail", "")
        if summary and settings.nova_welcome_enabled:
            await self._speak_response(summary)
        
        return result
    
    async def _speak_response(self, text: str) -> None:
        """Speak a response via TTS."""
        try:
            from .tts import say_nova_welcome
            # Reuse the TTS infrastructure for responses
            await asyncio.to_thread(self._synthesize_and_play, text)
        except Exception as e:
            log.warning("TTS failed: %s", e)
    
    def _synthesize_and_play(self, text: str) -> None:
        """Synthesize and play text via ElevenLabs TTS."""
        import numpy as np
        import sounddevice as sd
        from elevenlabs.client import ElevenLabs
        from .config import elevenlabs_env_config
        
        vid, model_id, output_format, pcm_rate = elevenlabs_env_config()
        if not vid:
            return
        
        api_key = settings.elevenlabs_api_key
        if not api_key:
            return
        
        try:
            client = ElevenLabs(api_key=api_key)
            chunks = client.text_to_speech.convert(
                voice_id=vid,
                text=text,
                model_id=model_id,
                output_format=output_format,
            )
            raw = b"".join(chunks)
            
            pcm_i16 = np.frombuffer(raw, dtype=np.int16)
            pcm_f = pcm_i16.astype(np.float32) / 32768.0
            sd.play(pcm_f, pcm_rate)
            sd.wait()
        except Exception as e:
            log.warning("TTS synthesis/playback failed: %s", e)
    
    async def stop(self) -> None:
        """Graceful shutdown of all components."""
        if not self._running:
            return
        
        log.info("Stopping Nova application...")
        self._running = False
        self._stop_event.set()
        
        # Stop event bus
        if self._event_bus:
            try:
                await self._event_bus.stop()
                log.info("Event bus stopped")
            except Exception as e:
                log.warning("Error stopping event bus: %s", e)
        
        log.info("Nova application stopped")
    
    async def __aenter__(self) -> "NovaApplication":
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.stop()


# Global application instance
_application: Optional[NovaApplication] = None


def get_application() -> NovaApplication:
    """Get or create the global NovaApplication instance."""
    global _application
    if _application is None:
        _application = NovaApplication()
    return _application


async def run_application() -> int:
    """
    Run the Nova application.
    Returns exit code (0 = success, 1 = error).
    """
    app = get_application()
    try:
        await app.start()
        await app.run()
        return 0
    except KeyboardInterrupt:
        log.info("Interrupted by user")
        return 0
    except Exception as e:
        log.error("Application error: %s", e)
        return 1
    finally:
        await app.stop()


def main() -> int:
    """Synchronous entry point for console scripts."""
    return asyncio.run(run_application())


if __name__ == "__main__":
    sys.exit(main())