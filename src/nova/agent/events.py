"""Event system for Agent Orchestrator."""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, Callable, List, Optional
from dataclasses import dataclass
from datetime import datetime
import asyncio


class ExecutionEventType(str, Enum):
    """Types of execution events."""
    EXECUTION_STARTED = "execution_started"
    EXECUTION_COMPLETED = "execution_completed"
    EXECUTION_FAILED = "execution_failed"
    ACTION_STARTED = "action_started"
    ACTION_COMPLETED = "action_completed"
    ACTION_FAILED = "action_failed"
    ACTION_RETRIED = "action_retried"
    EXECUTION_CANCELLED = "execution_cancelled"


@dataclass
class ExecutionEvent:
    """Event emitted during execution."""
    event_type: ExecutionEventType
    execution_id: str
    session_id: str
    timestamp: datetime = None
    data: dict = None
    
    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = __import__('datetime').datetime.utcnow()
        if self.data is None:
            self.data = {}


class EventEmitter:
    """Event emitter for execution events."""
    
    def __init__(self):
        self._listeners: dict[str, List[callable]] = {}
    
    def on(self, event_type: ExecutionEventType, callback: callable):
        """Register event listener."""
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(callback)
    
    def off(self, event_type: ExecutionEventType, callback: callable):
        """Remove event listener."""
        if event_type in self._listeners:
            try:
                self._listeners[event_type].remove(callback)
            except ValueError:
                pass
    
    def emit(self, event_type: ExecutionEventType, data: dict = None, execution_id: str = "", session_id: str = ""):
        """Emit event to all listeners."""
        from datetime import datetime
        event = ExecutionEvent(
            event_type=event_type,
            execution_id=event_id,
            session_id=session_id,
            data=data or {}
        )
        
        if event_type in self._listeners:
            for callback in self._listeners[event_type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        asyncio.create_task(callback(event))
                    else:
                        callback(event)
                except Exception as e:
                    # Log error but don't break other listeners
                    import logging
                    logging.getLogger(__name__).error(f"Event listener error: {e}")
    
    def clear(self, event_type: ExecutionEventType = None):
        """Clear listeners."""
        if event_type:
            self._listeners[event_type] = []
        else:
            self._listeners.clear()


# Global event emitter
_global_emitter = None


def get_event_emitter() -> EventEmitter:
    """Get global event emitter."""
    global _global_emitter
    if _global_emitter is None:
        _global_emitter = EventEmitter()
    return _global_emitter