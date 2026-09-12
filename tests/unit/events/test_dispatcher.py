"""
Unit tests for Dispatcher.
"""
import asyncio
import pytest
from nova.events.dispatcher import Dispatcher, DispatchMetrics
from nova.events.events import BaseEvent


@pytest.fixture()
def dispatcher():
    d = Dispatcher()
    yield d
    asyncio.run(d.stop())


@pytest.mark.asyncio
async def test_dispatcher_start_stop(dispatcher):
    await dispatcher.start()
    assert dispatcher._running
    await dispatcher.stop()
    assert not dispatcher._running


@pytest.mark.asyncio
async def test_dispatch_single_listener(dispatcher):
    await dispatcher.start()
    received = []

    def listener(ev):
        received.append(ev)

    from nova.events.events import BaseEvent
    evt = BaseEvent(source="test", category="test")
    await dispatcher.dispatch(evt, [listener])
    await asyncio.sleep(0.02)
    assert len(received) == 1
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_async_listener(dispatcher):
    await dispatcher.start()
    received = []

    async def alistener(ev):
        await asyncio.sleep(0.01)
        received.append(ev)

    from nova.events.events import BaseEvent
    evt = BaseEvent(source="test", category="test")
    await dispatcher.dispatch(evt, [{"callback": alistener, "async_mode": True, "filters": [], "priority": 0, "once": False}])
    await asyncio.sleep(0.05)
    assert len(received) == 1
    await dispatcher.stop()


@pytest.mark.asyncio
async def test_exception_isolation(dispatcher):
    await dispatcher.start()
    good = []
    bad = []

    def good_listener(ev):
        good.append(ev)

    def bad_listener(ev):
        raise RuntimeError("boom")

    from nova.events.events import BaseEvent
    evt = BaseEvent(source="test", category="test")
    # The dispatcher expects listener entries with fields; we'll use internal _ListenerEntry
    from nova.events.event_bus import _ListenerEntry
    await dispatcher.dispatch(
        evt,
        [
            _ListenerEntry(callback=good_listener, event_type=BaseEvent, async_mode=False, filters=[], priority=0, once=False),
            _ListenerEntry(callback=bad_listener, event_type=BaseEvent, async_mode=False, filters=[], priority=0, once=False),
        ]
    )
    await asyncio.sleep(0.02)
    assert len(good) == 1
    await dispatcher.stop()