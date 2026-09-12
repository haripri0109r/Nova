"""
Performance benchmark for EventBus.
"""
import asyncio
import time
import pytest
from nova.events import get_event_bus, BaseEvent


@pytest.mark.performance
@pytest.mark.asyncio
async def test_throughput():
    bus = get_event_bus()
    await bus.start()
    n = 100_000
    received = 0

    def listener(ev):
        nonlocal received
        received += 1

    bus.subscribe(BaseEvent, listener)
    start = time.perf_counter()
    for _ in range(n):
        bus.publish(BaseEvent(source="perf", category="perf"))
    await asyncio.sleep(0.5)  # allow processing
    elapsed = time.perf_counter() - start
    throughput = n / elapsed
    print(f"Throughput: {throughput:.0f} events/sec")
    assert throughput > 50000  # at least 50k eps
    await bus.stop()