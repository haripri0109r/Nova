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
    Event bus – no singleton, each call to get_event_bus() returns a new instance.
    """
    _instances: List["EventBus"] = []

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
        if self._running:
            return
        self._loop = asyncio.get_running_loop()
        # Reinitialize asyncio primitives on the current loop
        self._lock = asyncio.Lock()
        # Register globally decorated listeners
        from .listeners import listener_registry
        for entry_data in listener_registry.get_entries():
            entry = _ListenerEntry(**entry_data)
            target = self._wildcards if entry.event_type == "*" else self._listeners[entry.event_type]
            idx = 0
            for i, e in enumerate(target):
                if e.priority < entry.priority:
                    idx = i
                    break
            else:
                idx = len(target)
            target.insert(idx, entry)
        # Register this instance
        EventBus._instances.append(self)
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
        # Remove from instances
        try:
            EventBus._instances.remove(self)
        except ValueError:
            pass
        logger.info("EventBus stopped")

    async def _stop_on_original_loop(self) -> None:
        await self._dispatcher.stop()
        await self._scheduler.stop()

    async def publish(self, event: BaseEvent, *, delay: float = 0.0) -> None:
        """
        Publish an event. If delay > 0, schedule for later.
        This method is asynchronous; it awaits the dispatch of all listeners.
        """
        if delay > 0:
            await self._schedule_delayed(event, delay)
            return
        # Ensure bus is started
        if not self._running:
            await self.start()
        # Run dispatch and await completion
        await self._dispatch_now(event)

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
                    sync_calls.append(entry.callback)
            except Exception:
                logger.exception("Listener %s raised during scheduling", entry.callback)

        # Run sync callbacks in thread pool
        if sync_calls:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = asyncio.get_event_loop()
            await asyncio.gather(*[loop.run_in_executor(None, cb, event) for cb in sync_calls])

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


def get_event_bus() -> EventBus:
    return EventBus()