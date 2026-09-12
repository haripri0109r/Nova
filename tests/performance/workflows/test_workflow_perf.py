"""
Performance benchmarks for WorkflowEngine.
"""
import asyncio
import time
import pytest
from nova.workflows import get_workflow_engine, Workflow, ActionNode
from nova.skills.base import BaseSkill
from nova.skills.registry import registry


class PerfSkill(BaseSkill):
    intent = "perf_tool"
    description = "Lightweight deterministic skill for performance testing."

    def can_handle(self, intent_data):
        return intent_data.get("intent") == "perf_tool"

    def execute(self, intent_data):
        return {"ok": True}


@pytest.mark.performance
@pytest.mark.asyncio
async def test_sequential_workflow_throughput():
    # Register lightweight test skill
    perf_skill = PerfSkill()
    registry.register(perf_skill)

    engine = get_workflow_engine()
    await engine.start()
    n = 1000

    wf = Workflow(name="perf_test")
    for i in range(10):
        node = ActionNode(name=f"step_{i}", tool="perf_tool", args={"i": i})
        if i > 0:
            wf.add_edge(f"step_{i-1}", f"step_{i}")
        wf.add_node(node)

    start = time.perf_counter()
    tasks = [engine.run_workflow(wf) for _ in range(n)]
    await asyncio.gather(*tasks)
    await asyncio.sleep(0.5)

    elapsed = time.perf_counter() - start
    throughput = n / elapsed
    print(f"Workflow throughput: {throughput:.0f} workflows/sec")
    assert throughput > 100  # at least 100 workflows/sec

    await engine.stop()
    # Cleanup
    registry._skills.pop("perf_tool", None)