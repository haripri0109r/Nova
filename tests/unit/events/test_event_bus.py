"""
Unit and concurrency tests for EventBus.
"""
import asyncio
import pytest
import pytest_asyncio
from nova.events import get_event_bus, BatteryLowEvent, BaseEvent, Priority
from nova.events.event_bus import EventBus


@pytest_asyncio.fixture
async def bus():
    b = EventBus()
    await b.start()
    yield b
    await b.stop()


@pytest.mark.asyncio
async def test_publish_sync_listener(bus):
    received = []

    def listener(ev):
        received.append(ev)

    unsub = bus.subscribe(BaseEvent, listener)
    evt = BaseEvent(source="test", category="test")
    await bus.publish(evt)
    await asyncio.sleep(0.05)
    assert len(received) == 1
    assert received[0].event_id == evt.event_id
    unsub()


@pytest.mark.asyncio
async def test_publish_async_listener(bus):
    received = []

    async def alistener(ev):
        await asyncio.sleep(0.01)
        received.append(ev)

    bus.subscribe(BaseEvent, alistener, async_mode=True)
    evt = BaseEvent(source="test", category="test")
    await bus.publish(evt)
    await asyncio.sleep(0.05)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_priority_ordering(bus):
    order = []

    def low(ev):
        order.append("low")

    def high(ev):
        order.append("high")

    bus.subscribe(BaseEvent, low, priority=0)
    bus.subscribe(BaseEvent, high, priority=10)

    await bus.publish(BaseEvent(source="t", category="c"))
    await asyncio.sleep(0.05)
    assert order == ["high", "low"]


@pytest.mark.asyncio
async def test_filter(bus):
    results = []

    def filtered(ev):
        if ev.payload.get("important"):
            results.append(ev)

    bus.subscribe(BaseEvent, filtered, filters=[lambda e: e.payload.get("important")])
    await bus.publish(BaseEvent(source="t", category="c", payload={"important": True}))
    await bus.publish(BaseEvent(source="t", category="c", payload={"important": False}))
    await asyncio.sleep(0.02)
    assert len(results) == 1


@pytest.mark.asyncio
async def test_wildcard(bus):
    events = []

    def wild(ev):
        events.append(ev)

    bus.subscribe("*", wild)
    await bus.publish(BaseEvent(source="a", category="a"))
    await bus.publish(BaseEvent(source="b", category="b"))
    await asyncio.sleep(0.02)
    assert len(events) == 2


@pytest.mark.asyncio
async def test_delayed_event(bus):
    received = []

    def listener(ev):
        received.append(ev)

    bus.subscribe(BaseEvent, listener)
    evt = BaseEvent(source="t", category="c")
    await bus.publish(evt, delay=0.05)
    await asyncio.sleep(0.02)
    assert len(received) == 0
    await asyncio.sleep(0.1)
    assert len(received) == 1


@pytest.mark.asyncio
async def test_once_listener(bus):
    count = []

    def listener(ev):
        count.append(ev)

    bus.subscribe(BaseEvent, listener, once=True)
    await bus.publish(BaseEvent(source="t", category="c"))
    await bus.publish(BaseEvent(source="t", category="c"))
    await asyncio.sleep(0.02)
    assert len(count) == 1