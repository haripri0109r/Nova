"""
Scheduler – cron, interval, one‑shot, startup, shutdown jobs.
"""
from __future__ import annotations
import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger("nova.events.scheduler")


@dataclass
class ScheduledJob:
    func: Callable[..., Any]
    trigger: str                     # "cron", "interval", "date", "startup", "shutdown"
    # cron fields
    cron_expr: Optional[str] = None
    # interval fields
    seconds: Optional[int] = None
    minutes: int = 0
    hours: int = 0
    # date trigger
    run_date: Optional[float] = None
    # common
    id: Optional[str] = None
    kwargs: Dict[str, Any] = field(default_factory=dict)


class Scheduler:
    """
    Thin wrapper around APScheduler asyncio scheduler.
    """
    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._jobs: Dict[str, Any] = {}
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._running = False

    async def start(self) -> None:
        if self._running or self._scheduler.running:
            return
        self._loop = asyncio.get_running_loop()
        self._scheduler.start()
        self._running = True
        logger.info("Scheduler started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._loop.is_closed():
            return
        current_loop = asyncio.get_running_loop()
        if current_loop is self._loop:
            await self._shutdown_on_original_loop()
        else:
            future = asyncio.run_coroutine_threadsafe(self._shutdown_on_original_loop(), self._loop)
            await asyncio.wrap_future(future)

    async def _shutdown_on_original_loop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=True)
            # wait until the scheduler is actually stopped
            while self._scheduler.running:
                await asyncio.sleep(0.01)

    def add_job(self, job: ScheduledJob) -> str:
        job_id = job.id or uuid.uuid4().hex
        trigger = self._build_trigger(job)
        self._scheduler.add_job(
            func=job.func,
            trigger=trigger,
            id=job_id,
            kwargs=job.kwargs,
            replace_existing=True,
        )
        self._jobs[job_id] = job
        logger.debug("Scheduled job %s with trigger %s", job_id, job.trigger)
        return job_id

    def remove_job(self, job_id: str) -> bool:
        try:
            self._scheduler.remove_job(job_id)
            self._jobs.pop(job_id, None)
            logger.debug("Removed job %s", job_id)
            return True
        except Exception:
            logger.warning("Failed to remove job %s", job_id)
            return False

    def get_jobs(self) -> List[ScheduledJob]:
        return list(self._jobs.values())

    # ------------------------------------------------------------------
    # Trigger builders
    # ------------------------------------------------------------------
    def _build_trigger(self, job: ScheduledJob):
        if job.trigger == "cron":
            if not job.cron_expr:
                raise ValueError("cron_expr required for cron trigger")
            return CronTrigger.from_crontab(job.cron_expr)
        if job.trigger == "interval":
            return IntervalTrigger(seconds=job.seconds, minutes=job.minutes, hours=job.hours, start_date=datetime.now())
        if job.trigger == "date":
            if job.run_date is None:
                raise ValueError("run_date required for date trigger")
            # Convert float timestamp to datetime if necessary
            run_date = job.run_date
            if isinstance(run_date, (int, float)):
                run_date = datetime.fromtimestamp(run_date)
            return DateTrigger(run_date=run_date)
        if job.trigger in ("startup", "shutdown"):
            # Handled externally via event bus hooks
            return None
        raise ValueError(f"Unsupported trigger {job.trigger}")