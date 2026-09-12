"""
Stress tests for WorkflowEngine.
"""
import asyncio
import time
import pytest
from nova.workflows import get_workflow_engine, Workflow, ActionNode, ParallelNode
from nova.skills.base import BaseSkill
from nova.skills.registry import registry


class StressSkill(BaseSkill):
    intent = "stress_tool"
    description = "Lightweight deterministic skill for stress testing."

    def can_handle(self, intent_data):
        return intent_data.get("intent") == "stress_tool"

    def execute(self, intent_data):
        return {"ok": True}


@pytest.mark.stress
@pytest.mark.asyncio
async def test_concurrent_workflows():
    # Register lightweight test skill
    stress_skill = StressSkill()
    registry.register(stress_skill)

    engine = get_workflow_engine()
    await engine.start()

    async def run_many():
        tasks = []
        for i in range(100):
            wf = Workflow(name=f"stress_{i}")
            for j in range(5):
                node = ActionNode(name=f"step_{j}", tool="stress_tool", args={"j": j})
                if j > 0:
                    wf.add_edge(f"step_{j-1}", f"step_{j}")
                wf.add_node(node)
            tasks.append(engine.run_workflow(wf))
        await asyncio.gather(*tasks)
        await asyncio.sleep(0.5)

    start = time.perf_counter()
    await run_many()
    elapsed = time.perf_counter() - start
    print(f"100 workflows completed in {elapsed:.2f}s")
    assert elapsed < 10.0  # Should complete within 10 seconds

    # Verify cleanup
    assert len(engine._running_workflows) == 0

    await engine.stop()
    # Cleanup
    registry._skills.pop("stress_tool", None)