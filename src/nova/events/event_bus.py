"""
Central EventBus – thread‑safe, async‑first, priority‑aware, with
delayed / scheduled / wildcard support.
"""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Awaitable, Dict, List, Optional, Type, Union

from .events import BaseEvent, Priority, ScheduledEvent
from .dispatcher import Dispatcher, _ListenerEntry, DispatchMetrics
from .scheduler import Scheduler, ScheduledJob
from .listeners import ListenerRegistry, on as _on_decorator

logger = logging.getLogger("nova.events.bus")


class EventBus:
    """
    Central EventBus – singleton per process.
    """
    _instance: Optional["EventBus"] = None
    # _lock removed - using threading lock in get_event_bus()

    def __new__(cls) -> "EventBus":
        if cls._instance is None:
            instance = super().__new__(cls)
            cls._instance = instance
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialised", False):
            return
        self._listeners: Dict[Union[Type[BaseEvent], str], List[_ListenerEntry]] = defaultdict(list)
        self._wildcards: List[_ListenerEntry] = []
        self._dispatcher = Dispatcher()
        self._scheduler = Scheduler()
        self._metrics = DispatchMetrics()
        self._running = False
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._initialised = True
        logger.info("EventBus initialised")

    async def start(self) -> None:
        current_loop = asyncio.get_running_loop()
        if self._running and self._loop is current_loop:
            return
        # If loop changed, reset state
        if self._loop is not None and self._loop is not current_loop:
            # Loop changed - need to reinitialize on new loop
            self._loop = current_loop
            self._running = False
            self._listeners.clear()
            self._wildcards.clear()
            # Recreate dispatcher and scheduler for new loop
            from .dispatcher import Dispatcher
            from .scheduler import Scheduler
            self._dispatcher = Dispatcher()
            self._scheduler = Scheduler()
            self._lock = asyncio.Lock()
        
        if self._running:
            return
        self._loop = current_loop
        # Reinitialize asyncio primitives on the current loop
        self._lock = asyncio.Lock()
        # Register globally decorated listeners
        from .listeners import listener_registry
        for entry_data in listener_registry.get_entries():
            entry = _ListenerEntry(**entry_data)
            target = self._wildcards if entry.event_type == "*" else self._listeners[entry.event_type]
            # Avoid duplicate registration of same callback
            if any(e.callback is entry.callback for e in target):
                continue
            idx = 0
            for i, e in enumerate(target):
                if e.priority < entry.priority:
                    idx = i
                    break
            else:
                idx = len(target)
            target.insert(idx, entry)
        await self._dispatcher.start()
        await self._scheduler.start()
        self._running = True
        logger.info("EventBus started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._loop.is_closed():
            return
        current_loop = asyncio.get_running_loop()
        if current_loop is self._loop:
            await self._dispatcher.stop()
            await self._scheduler.stop()
        else:
            future = asyncio.run_coroutine_threadsafe(self._stop_on_original_loop(), self._loop)
            await asyncio.wrap_future(future)
        # Clear all listeners and state
        self._listeners.clear()
        self._wildcards.clear()
        logger.info("EventBus stopped")

    async def _stop_on_original_loop(self) -> None:
        await self._dispatcher.stop()
        await self._scheduler.stop()

    def publish(self, event: BaseEvent, *, delay: float = 0.0) -> asyncio.Task:
        """
        Publish an event. If delay > 0, schedule for later.
        Returns a Task that can be awaited to wait for dispatch completion.
        The dispatch runs in the background regardless of whether the task is awaited.
        """
        if delay > 0:
            # For delayed events, we need to schedule on the event loop
            if self._loop and not self._loop.is_closed():
                task = asyncio.run_coroutine_threadsafe(self._schedule_delayed(event, delay), self._loop)
                # Wrap in a Task-like object
                return asyncio.wrap_future(task)
            return asyncio.create_task(asyncio.sleep(0))  # dummy task
        # Ensure bus is started
        if not self._running:
            # Start synchronously if not running - this is a best effort
            if self._loop and not self._loop.is_closed():
                asyncio.run_coroutine_threadsafe(self.start(), self._loop)
            else:
                # No loop available, can't start
                logger.warning("EventBus not started and no event loop available")
                return asyncio.create_task(asyncio.sleep(0))
        # Fire and forget - schedule dispatch as background task
        if self._loop and not self._loop.is_closed():
            try:
                # Try to get the current running loop - if we're in the same thread, use create_task
                current_loop = asyncio.get_running_loop()
                if current_loop is self._loop:
                    # Same loop - use create_task directly (much faster)
                    return current_loop.create_task(self._dispatch_now(event))
                else:
                    # Different loop - use run_coroutine_threadsafe
                    future = asyncio.run_coroutine_threadsafe(self._dispatch_now(event), self._loop)
                    return asyncio.wrap_future(future)
            except RuntimeError:
                # No running loop - use run_coroutine_threadsafe
                future = asyncio.run_coroutine_threadsafe(self._dispatch_now(event), self._loop)
                return asyncio.wrap_future(future)
        return asyncio.create_task(asyncio.sleep(0))  # dummy task

    async def _dispatch_now(self, event: BaseEvent) -> None:
        listeners = self._match_listeners(event)
        if not listeners:
            logger.debug("No listeners for %s", event.__class__.__name__)
            return

        # Remove once listeners before invoking so they won't fire again
        once_entries = [e for e in listeners if e.once]
        for entry in once_entries:
            self.unsubscribe(entry.callback)

        sync_calls = []
        async_tasks = []
        for entry in listeners:
            try:
                if entry.async_mode:
                    # Schedule async listener as a task
                    coro = entry.callback(event)
                    if asyncio.iscoroutine(coro):
                        task = asyncio.create_task(coro)
                        async_tasks.append(task)
                    elif isinstance(coro, asyncio.Task):
                        # Already a task, keep reference
                        pass
                    else:
                        # Fallback: assume coroutine
                        async_tasks.append(asyncio.create_task(coro))
                else:
                    # Run sync callbacks directly in event loop (not thread pool)
                    # This allows them to use asyncio.create_task if needed
                    sync_calls.append(entry.callback)
            except Exception:
                logger.exception("Listener %s raised during scheduling", entry.callback)

        # Run sync callbacks directly in event loop
        if sync_calls:
            for cb in sync_calls:
                try:
                    cb(event)
                except Exception:
                    logger.exception("Sync listener %s raised", cb)

        # Await all async listener tasks
        if async_tasks:
            await asyncio.gather(*async_tasks, return_exceptions=True)

    async def _schedule_delayed(self, event: BaseEvent, delay: float) -> None:
        run_time = time.time() + delay
        # schedule a job that runs on the event loop via run_coroutine_threadsafe
        job = ScheduledJob(
            func=lambda: asyncio.run_coroutine_threadsafe(self._dispatch_now(event), self._loop),
            trigger="date",
            run_date=datetime.fromtimestamp(time.time() + delay),
            id=f"delayed_{uuid.uuid4().hex}",
        )
        self._scheduler.add_job(job)
        logger.debug("Scheduled delayed event %s in %.2fs", event.__class__.__name__, delay)

    def subscribe(
        self,
        event_type: Union[Type[BaseEvent], str],
        callback: Callable[[BaseEvent], Union[None, Awaitable[None]]],
        *,
        priority: int = 0,
        filters: Optional[List[Callable[[BaseEvent], bool]]] = None,
        async_mode: bool = False,
        once: bool = False,
    ) -> Callable[[], None]:
        """
        Returns an unsubscribe callable.
        """
        entry = _ListenerEntry(
            callback=callback,
            event_type=event_type,
            priority=priority,
            filters=filters or [],
            async_mode=async_mode,
            once=once,
        )
        target = self._wildcards if event_type == "*" else self._listeners[event_type]
        idx = 0
        for i, e in enumerate(target):
            if e.priority < priority:
                idx = i
                break
        else:
            idx = len(target)
        target.insert(idx, entry)

        def _unsub():
            self.unsubscribe(callback)
            # Also remove from global listener registry if present
            try:
                from .listeners import listener_registry
                listener_registry.remove_callback(callback)
            except Exception:
                pass
        # Attach unsubscribe to the callback for test compatibility
        try:
            callback._nova_unsubscribe = _unsub
        except AttributeError:
            pass
        return _unsub

    def unsubscribe(self, callback: Callable) -> bool:
        removed = False
        for lst in (self._listeners.values(), [self._wildcards]):
            for l in lst:
                for i, e in enumerate(l):
                    if e.callback is callback:
                        l.pop(i)
                        removed = True
                        break
        return removed

    def _match_listeners(self, event: BaseEvent) -> List[_ListenerEntry]:
        matches: List[_ListenerEntry] = []
        for etype, lst in self._listeners.items():
            if isinstance(etype, type) and isinstance(event, etype):
                matches.extend(lst)
        matches.extend(self._wildcards)

        filtered = [e for e in matches if all(f(event) for f in e.filters)]
        filtered.sort(key=lambda e: -e.priority)
        return filtered

    def schedule_job(self, job: ScheduledJob) -> str:
        return self._scheduler.add_job(job)

    @property
    def metrics(self) -> DispatchMetrics:
        return self._metrics


# Singleton accessor
_event_bus_lock = None

def get_event_bus() -> EventBus:
    """Return the process‑wide EventBus instance, creating it on first call."""
    global _event_bus_lock
    if EventBus._instance is None:
        # Double-checked locking pattern for thread safety
        if _event_bus_lock is None:
            import threading
            _event_bus_lock = threading.Lock()
        with _event_bus_lock:
            if EventBus._instance is None:
                EventBus._instance = EventBus()
    return EventBus._instance


# Backward‑compatible synchronous accessor (creates if needed)
def get_event_bus_sync() -> EventBus:
    """Synchronous accessor used by legacy code; creates the bus if needed."""
    return get_event_bus()