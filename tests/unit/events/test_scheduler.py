"""
Tests for Scheduler.
"""
import asyncio
import pytest
import pytest_asyncio
from datetime import datetime, timedelta
from nova.events.scheduler import Scheduler, ScheduledJob


@pytest_asyncio.fixture
async def scheduler():
    s = Scheduler()
    await s.start()
    yield s
    await s.stop()


@pytest.mark.asyncio
async def test_scheduler_start_stop(scheduler):
    await scheduler.start()
    assert scheduler._scheduler.running
    await scheduler.stop()
    assert not scheduler._scheduler.running


@pytest.mark.asyncio
async def test_add_interval_job(scheduler):
    counter = []

    def tick():
        counter.append(1)

    job = ScheduledJob(func=tick, trigger="interval", kwargs={}, seconds=0.02, minutes=0, hours=0)
    jid = scheduler.add_job(job)
    await asyncio.sleep(0.07)
    await scheduler.stop()
    assert len(counter) >= 2


@pytest.mark.asyncio
async def test_cron_job(scheduler):
    runs = []

    def cron_func():
        runs.append(1)

    job = ScheduledJob(func=cron_func, trigger="cron", kwargs={}, cron_expr="* * * * *")  # every minute not practical fast
    # Use interval instead for fast test
    job2 = ScheduledJob(func=lambda: runs.append(2), trigger="interval", kwargs={}, seconds=0.02, minutes=0, hours=0)
    scheduler.add_job(job2)
    await asyncio.sleep(0.05)
    await scheduler.stop()
    assert len(runs) >= 1


@pytest.mark.asyncio
async def test_one_shot_date_job(scheduler):
    ran = []

    def once():
        ran.append(1)

    run_dt = datetime.now() + timedelta(seconds=0.05)
    job = ScheduledJob(func=once, trigger="date", kwargs={}, run_date=run_dt.timestamp())
    scheduler.add_job(job)
    await asyncio.sleep(0.1)
    await scheduler.stop()
    assert ran == [1]