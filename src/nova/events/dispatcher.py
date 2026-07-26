"""
Dispatcher – priority queue, parallel async listeners, timeouts,
exception isolation, metrics.
"""
from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, List, Optional, Union, Type

from .events import BaseEvent, Priority

logger = logging.getLogger("nova.events.dispatcher")


@dataclass
class _ListenerEntry:
    callback: Callable[[BaseEvent], Union[None, Awaitable[None]]]
    event_type: Union[Type[BaseEvent], str]          # str for wildcard "*"
    priority: int = 0
    filters: List[Callable[[BaseEvent], bool]] = field(default_factory=list)
    async_mode: bool = False
    once: bool = False


@dataclass
class DispatchMetrics:
    total_dispatched: int = 0
    total_errors: int = 0
    total_latency_ms: float = 0.0
    last_dispatch_ts: Optional[float] = None


class Dispatcher:
    """
    Internal dispatcher used by EventBus.
    """
    def __init__(self, max_concurrent: int = 64, default_timeout: float = 5.0) -> None:
        self._max_concurrent = max_concurrent
        self._default_timeout = default_timeout
        self._running = False
        self._worker_task: Optional[asyncio.Task] = None
        # These will be initialized in start()
        self._queue: Optional[asyncio.PriorityQueue] = None
        self._sem: Optional[asyncio.Semaphore] = None
        self._lock: Optional[asyncio.Lock] = None
        self._metrics = DispatchMetrics()

    async def start(self) -> None:
        if self._running:
            return
        # Create asyncio primitives on the current running loop
        self._queue = asyncio.PriorityQueue()
        self._sem = asyncio.Semaphore(self._max_concurrent)
        self._lock = asyncio.Lock()
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.debug("Dispatcher started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.debug("Dispatcher stopped")

    async def dispatch(
        self,
        event: "BaseEvent",
        listeners: List[Union[_ListenerEntry, Callable[[BaseEvent], Union[None, Awaitable[None]]], Dict]],
        *,
        timeout: Optional[float] = None,
    ) -> None:
        # Normalize listeners to _ListenerEntry
        normalized: List[_ListenerEntry] = []
        for l in listeners:
            if isinstance(l, _ListenerEntry):
                normalized.append(l)
            elif callable(l):
                normalized.append(_ListenerEntry(callback=l, event_type="*", async_mode=False))
            elif isinstance(l, dict):
                # assume dict contains keys matching _ListenerEntry fields
                d = dict(l)  # copy
                d.setdefault("event_type", "*")
                normalized.append(_ListenerEntry(**d))
            else:
                raise TypeError(f"Unsupported listener type: {type(l)}")
        priority = -int(event.priority)
        await self._queue.put((priority, time.time(), event, normalized, timeout or self._default_timeout))

    async def _worker(self) -> None:
        while True:
            try:
                priority, enq_ts, event, listeners, timeout = await self._queue.get()
                await self._run_listeners(event, listeners, timeout)
                self._queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Dispatcher worker error")

    async def _run_listeners(
        self,
        event: "BaseEvent",
        listeners: List[_ListenerEntry],
        timeout: float,
    ) -> None:
        async with self._sem:
            start = time.perf_counter()
            tasks: List[asyncio.Task] = []
            for entry in listeners:
                coro = self._safe_call(entry, event)
                tasks.append(asyncio.create_task(coro))

            if tasks:
                try:
                    await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("Dispatch of %s timed out after %.2fs", event.__class__.__name__, timeout)

            elapsed = (time.perf_counter() - start) * 1000
            self._metrics.total_dispatched += 1
            self._metrics.total_latency_ms += elapsed
            self._metrics.last_dispatch_ts = time.time()

    async def _safe_call(self, entry: _ListenerEntry, event: BaseEvent) -> None:
        try:
            if entry.async_mode:
                await entry.callback(event)
            else:
                await asyncio.to_thread(entry.callback, event)
        except Exception:
            logger.exception("Listener %s raised", entry.callback)
            self._metrics.total_errors += 1

    @property
    def metrics(self) -> DispatchMetrics:
        return self._metrics