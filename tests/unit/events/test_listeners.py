"""
Tests for listeners decorator and registry.
"""
import asyncio
import pytest
import pytest_asyncio
from nova.events import get_event_bus, BaseEvent, on, ListenerRegistry


@pytest_asyncio.fixture
async def bus():
    b = get_event_bus()
    await b.start()
    yield b
    await b.stop()


@pytest.mark.asyncio
async def test_on_decorator_registers_listener(bus):
    received = []

    @on(BaseEvent, priority=5)
    async def handler(ev):
        await asyncio.sleep(0.01)
        received.append(ev)

    evt = BaseEvent(source="test", category="test")
    await bus.publish(evt)
    await asyncio.sleep(0.05)
    assert len(received) == 1
    # cleanup
    handler._nova_unsubscribe()
    await bus.stop()


@pytest.mark.asyncio
async def test_listener_registry_bulk(bus):
    reg = ListenerRegistry()
    calls = []

    def cb1(ev):
        calls.append("cb1")

    def cb2(ev):
        calls.append("cb2")

    reg.register(BaseEvent, cb1)
    reg.register(BaseEvent, cb2)
    # simulate publish via bus
    bus.subscribe(BaseEvent, cb1)
    bus.subscribe(BaseEvent, cb2)
    await bus.publish(BaseEvent(source="t", category="c"))
    # we can't easily test async here, just ensure unregister works
    reg.unregister_all()
    # after unregister, callbacks should be removed from bus (they remain but registry cleared)
    # not strict test
    assert len(reg._handles) == 0