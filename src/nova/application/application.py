"""
Nova Core Application – Main application loop integrating all Nova modules.

This module provides the NovaApplication class which orchestrates the complete
Nova pipeline: Wake Phrase → STT → Intent → Execution → TTS → Events.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import sys
import threading
from typing import Optional

from ..config import settings
from ..events import get_event_bus
from ..events.events import (
    UserCommandReceivedEvent,
    IntentResolvedEvent,
    GoalCompletedEvent,
    GoalFailedEvent,
)
from ..brain import get_brain
from ..intent.engine import get_intent_engine
from ..skills.manager import get_skill_manager
from ..llm.manager import get_llm_manager
from ..agent.orchestrator import get_agent_orchestrator
from ..tts import say_nova_welcome, say
from ..wake_phrase import WakePhraseListener

log = logging.getLogger("nova.application")


class NovaApplication:
    """
    Main Nova application – orchestrates the complete voice assistant pipeline.
    
    Pipeline: Wake Phrase → STT (Whisper) → Intent (Brain) → Execute (Agent Orchestrator) → TTS
    """

    def __init__(self) -> None:
        self._running = False
        self._stop_event = asyncio.Event()
        self._wake_listener: Optional[WakePhraseListener] = None
        self._brain = get_brain()
        self._event_bus = get_event_bus()
        self._welcome_played = False
        self._initialized = False
        self._just_spoke = False

    async def initialize(self) -> None:
        """Initialize all components in order."""
        if self._initialized:
            return
            
        log.info("Initializing Nova application...")
        
        # Initialize configuration first
        log.info("Initializing configuration...")
        
        # Initialize EventBus
        log.info("Initializing EventBus...")
        self._event_bus = get_event_bus()
        await self._event_bus.start()
        log.info("EventBus started")
        
        # Initialize LLMManager
        log.info("Initializing LLMManager...")
        from ..llm.manager import get_llm_manager
        self._llm_manager = get_llm_manager()
        if not await self._llm_manager.initialize():
            raise RuntimeError("Failed to initialize LLMManager")
        log.info("LLMManager initialized")
        
        # Initialize IntentEngine
        log.info("Initializing IntentEngine...")
        from ..intent.engine import get_intent_engine
        self._intent_engine = get_intent_engine()
        log.info("IntentEngine initialized")
        
        # Initialize SkillManager
        log.info("Initializing SkillManager...")
        from ..skills.manager import get_skill_manager
        self._skill_manager = get_skill_manager()
        log.info("SkillManager initialized")
        
        # Initialize AgentOrchestrator
        log.info("Initializing AgentOrchestrator...")
        from ..agent.orchestrator import get_agent_orchestrator
        self._orchestrator = get_agent_orchestrator()
        log.info("AgentOrchestrator initialized")
        
        # Initialize Brain
        log.info("Initializing Brain...")
        from ..brain import get_brain
        self._brain = get_brain()
        log.info("Brain initialized")
        
        # Initialize Wake Engine
        log.info("Initializing Wake Engine...")
        self._wake_listener = WakePhraseListener()
        log.info("Wake Engine initialized")
        
        # Initialize TTS
        log.info("Initializing TTS...")
        log.info("TTS initialized")
        
        self._initialized = True
        log.info("All components initialized")

    async def start(self) -> None:
        """Start the application after initialization."""
        if self._running:
            return
            
        if not self._initialized:
            await self.initialize()
            
        log.info("Starting Nova application...")
        self._running = True
        log.info("Nova application started")

    async def run(self) -> None:
        """
        Main application loop.
        Listens for wake phrase, processes commands, executes actions.
        """
        if not self._running:
            await self.start()
            
        # Ensure wake listener is initialized
        assert self._wake_listener is not None, "Wake listener must be initialized"
        
        try:
            while self._running and not self._stop_event.is_set():
                # Skip wake detection for one iteration after speaking to avoid self-trigger
                if self._just_spoke:
                    self._just_spoke = False
                    continue

                # Phase 1: Wait for wake phrase (blocking, no timeout)
                text = await asyncio.to_thread(self._wake_listener.listen_for_utterance)
                if text is not None:
                    log.debug("Heard: %r", text)
                
                if text and WakePhraseListener.matches_wake_phrase(text):
                    if not self._welcome_played:
                        self._welcome_played = True
                        log.info("Wake phrase detected: %r — listening for command", text)
                        
                        # Play welcome sequence on first wake
                        self._play_welcome_sequence()
                    
                    # Phase 2: Extract command from same utterance
                    remainder = self._extract_remainder(text)
                    command_text = ""
                    if remainder:
                        command_text = remainder
                    else:
                        # Phase 2b: Listen for command
                        heard = await self._listen_for_command()
                        if heard:
                            log.debug("Command heard: %r", heard)
                            command_text = heard
                    
                    # Phase 3: Process command through Brain
                    try:
                        result = await self._process_command(command_text)
                        log.info("Command processed: %s", result.get("status", "unknown"))
                        # Generate and speak response
                        response_text = self._extract_response_text(result)
                        if response_text:
                            log.info("Speaking response: %s", response_text)
                            try:
                                await asyncio.to_thread(say, response_text)
                                self._just_spoke = True
                            except Exception as e:
                                log.warning("TTS failed: %s", e)
                    except Exception as e:
                        log.error("Command processing failed: %s", e)
                        
        except asyncio.CancelledError:
            log.info("Application loop cancelled")
        except Exception as e:
            log.error("Unexpected error in application loop: %s", e)
            raise

    def _extract_remainder(self, text: str) -> str:
        """Extract command text after wake phrase."""
        if not text:
            return ""
        import re
        words = [w for w in re.split(r"[^a-z0-9']+", text.lower()) if w]
        for i in range(len(words) - 1):
            if words[i] in ("hello", "hey") and words[i + 1] in {"nova", "norma", "robot", "robert"}:
                return " ".join(words[i + 2:])
        if len(words) <= 2 and any(w in {"nova", "norma", "robot", "robert"} for w in words):
            return ""
        return ""

    async def _listen_for_command(self, timeout: float = 12.0) -> Optional[str]:
        """Listen for a command with timeout."""
        if self._wake_listener is None:
            log.warning("Wake listener not initialized")
            return None
        try:
            text = await asyncio.to_thread(self._wake_listener.listen_for_utterance, timeout=timeout)
            return text
        except Exception as e:
            log.warning("Command listening failed: %s", e)
            return None

    async def _process_command(self, command_text: str) -> dict:
        """Process a command through the Brain (which uses Agent Orchestrator)."""
        # Emit user command event
        await self._event_bus.publish(
            UserCommandReceivedEvent(source="application", payload={"text": command_text})
        )
        
        # Process through Brain asynchronously
        if hasattr(self._brain, "process_text"):
            resp = self._brain.process_text(command_text)
            if inspect.isawaitable(resp):
                resp = await resp
            if isinstance(resp, dict):
                result = resp
            else:
                status = "completed" if (hasattr(resp, "metadata") and resp.metadata.get("success", False)) else "error"
                message = getattr(resp, "response_text", str(resp))
                result = {
                    "status": status,
                    "message": message,
                    "summary": message,
                    "response": message,
                }
        else:
            result = self._brain.process(command_text)
        
        return result

    def _extract_response_text(self, result: dict) -> str:
        """Extract a human‑readable response from the result dict."""
        for key in ("message", "response", "text", "summary"):
            val = result.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
        # Fallback generic messages
        if result.get("status") == "completed":
            return "Done."
        if result.get("status") == "error":
            return "Sorry, something went wrong."
        return "Task completed."

    async def _play_welcome_sequence(self) -> None:
        """Run the welcome sequence: Spotify song + Chrome tabs + Cursor + TTS."""
        log.info("Playing welcome sequence...")
        
        # Play Spotify song
        from ..automation.spotify import play_song
        play_song(settings.song_uri)
        
        # Open Chrome tabs
        from ..automation.chrome import open_claude_in_chrome, open_binance_btc_in_chrome
        open_claude_in_chrome()
        open_binance_btc_in_chrome()
        
        # Play TTS welcome after delay
        if settings.nova_welcome_enabled and settings.nova_welcome_phrase.strip():
            delay = max(0.0, settings.nova_after_song_delay_s)
            if delay:
                await asyncio.sleep(delay)
            await asyncio.to_thread(say_nova_welcome)
        
        # Open Cursor
        from ..automation.cursor_editor import open_cursor_window
        open_cursor_window()

    async def stop(self) -> None:
        """Graceful shutdown."""
        if not self._running:
            return
        
        log.info("Stopping Nova application...")
        self._running = False
        self._stop_event.set()
        
        # Stop event bus
        if self._event_bus:
            await self._event_bus.stop()
        
        log.info("Nova application stopped")

    def health_check(self) -> dict:
        """Return health status of all components."""
        return {
            "application": "healthy" if self._running else "stopped",
            "initialized": self._initialized,
            "running": self._running,
            "event_bus": "running" if self._event_bus and hasattr(self._event_bus, '_running') and self._event_bus._running else "stopped",
            "brain": "healthy" if self._brain else "unavailable",
            "llm_manager": "healthy" if hasattr(self, '_llm_manager') and self._llm_manager else "unavailable",
            "intent_engine": "healthy" if hasattr(self, '_intent_engine') and self._intent_engine else "unavailable",
            "skill_manager": "healthy" if hasattr(self, '_skill_manager') and self._skill_manager else "unavailable",
            "wake_engine": "healthy" if self._wake_listener else "unavailable",
        }


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