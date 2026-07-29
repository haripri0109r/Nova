"""
Listener registry and decorator for declarative subscriptions.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Awaitable, List, Optional, Type, Union

from .events import BaseEvent

logger = logging.getLogger("nova.events.listeners")


class ListenerRegistry:
    """
    Holds listener metadata and provides decorator.
    """
    def __init__(self) -> None:
        self._entries: List[dict] = []
        self._handles: List[Callable[[], None]] = []

    def on(
        self,
        event_type: Union[Type[BaseEvent], str],
        *,
        priority: int = 0,
        filters: Optional[List[Callable[["BaseEvent"], bool]]] = None,
        async_mode: Optional[bool] = None,
        once: bool = False,
    ) -> Callable[[Callable[["BaseEvent"], Union[None, Awaitable[None]]]], Callable[["BaseEvent"], Union[None, Awaitable[None]]]]:
        """
        Decorator to register a listener.
        If async_mode is not explicitly set, it will be automatically detected
        by checking whether the decorated function is a coroutine function.
        """
        def decorator(func: Callable[["BaseEvent"], Union[None, Awaitable[None]]]) -> Callable[["BaseEvent"], Union[None, Awaitable[None]]]:
            # Auto-detect async_mode if not explicitly set
            detected_async = asyncio.iscoroutinefunction(func)
            effective_async = async_mode if async_mode is not None else detected_async
            self._entries.append({
                "callback": func,
                "event_type": event_type,
                "priority": priority,
                "filters": filters or [],
                "async_mode": effective_async,
                "once": once,
            })
            # Also subscribe to any already-running EventBus instances
            from .event_bus import EventBus
            for bus in EventBus._instances:
                if bus._running:
                    bus.subscribe(
                        event_type=event_type,
                        callback=func,
                        priority=priority,
                        filters=filters,
                        async_mode=effective_async,
                        once=once,
                    )
            return func
        return decorator

    def register(
        self,
        event_type: Union[Type[BaseEvent], str],
        callback: Callable[["BaseEvent"], Union[None, Awaitable[None]]],
        *,
        priority: int = 0,
        filters: Optional[List[Callable[["BaseEvent"], bool]]] = None,
        async_mode: bool = False,
        once: bool = False,
    ) -> None:
        """Programmatic registration returning an unsubscribe callable."""
        
        from .event_bus import get_event_bus
        bus = get_event_bus()
        unsub = bus.subscribe(
            event_type=event_type,
            callback=callback,
            priority=priority,
            filters=filters,
            async_mode=async_mode,
            once=once,
        )
        self._handles.append(unsub)

    def get_entries(self) -> List[dict]:
        return self._entries

    def clear(self) -> None:
        self._entries.clear()

    def unregister_all(self) -> None:
        for h in self._handles:
            try:
                h()
            except Exception:
                pass
        self._handles.clear()


# Global registry instance used by plugins and core modules
listener_registry = ListenerRegistry()

# Convenience decorator alias
on = listener_registry.on