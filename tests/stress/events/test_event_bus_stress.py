"""
Stress test for EventBus – many concurrent publishes and listeners.
"""
import asyncio
import pytest
from nova.events import get_event_bus, BaseEvent


@pytest.mark.stress
@pytest.mark.asyncio
async def test_concurrent_publish():
    bus = get_event_bus()
    await bus.start()
    results = asyncio.Queue()
    NUM_PUBLISHERS = 50
    EVENTS_PER = 200

    def listener(ev):
        asyncio.create_task(results.put(ev))

    bus.subscribe(BaseEvent, listener)

    async def publisher():
        for _ in range(EVENTS_PER):
            bus.publish(BaseEvent(source="stress", category="stress"))

    await asyncio.gather(*[publisher() for _ in range(NUM_PUBLISHERS)])
    # wait for processing
    await asyncio.sleep(0.5)
    count = 0
    while not results.empty():
        await results.get()
        count += 1
    expected = NUM_PUBLISHERS * EVENTS_PER
    assert count == expected, f"got {count}, expected {expected}"
    await bus.stop()