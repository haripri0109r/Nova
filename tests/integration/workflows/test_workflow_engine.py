"""
Integration tests for WorkflowEngine.
"""
import asyncio
import pytest

import nova.skills  # ensure skill registration side-effects
from nova.workflows import get_workflow_engine, Workflow, ActionNode, ParallelNode, ConditionNode
from nova.skills.registry import registry
from nova.skills.base import BaseSkill

# Capture real skills before any test clears the registry
_REAL_SKILLS = dict(registry._skills)


class MockVolumeSkill(BaseSkill):
    intent = "set_volume"
    description = "Mock volume control"
    def can_handle(self, intent_data):
        return intent_data.get("intent") == "set_volume"
    async def execute(self, intent_data):
        return {"status": "ok", "detail": "volume set"}


@pytest.fixture()
def engine():
    e = get_workflow_engine()
    yield e
    asyncio.run(e.stop())


@pytest.mark.asyncio
async def test_simple_workflow_execution(engine):
    # Restore real skills in case registry was cleared by other tests
    registry._skills.clear()
    registry._skills.update(_REAL_SKILLS)
    # Register mock volume skill to avoid pycaw dependency
    registry.register(MockVolumeSkill())

    await engine.start()
    wf = Workflow(name="simple_test")
    node = ActionNode(name="set_volume_action", tool="set_volume", args={"action": "set", "level": 50})
    wf.add_node(node)
    wf_task = engine.run_workflow(wf)
    wf_id = str(wf_task)
    await wf_task

    status = engine.get_workflow_status(wf_id)
    assert status["status"] == "completed"
    await engine.stop()


@pytest.mark.asyncio
async def test_parallel_execution(engine):
    # Restore real skills in case registry was cleared by other tests
    registry._skills.clear()
    registry._skills.update(_REAL_SKILLS)

    await engine.start()
    wf = Workflow(name="parallel_test")
    node1 = ActionNode(name="action1", tool="set_volume", args={"action": "set", "level": 10})
    node2 = ActionNode(name="action2", tool="set_volume", args={"action": "set", "level": 20})
    parallel = ParallelNode(name="parallel", children=[node1, node2])
    wf.add_node(parallel)

    wf_task = engine.run_workflow(wf)
    wf_id = str(wf_task)
    await wf_task

    status = engine.get_workflow_status(wf_id)
    assert status["status"] == "completed"
    await engine.stop()


@pytest.mark.asyncio
async def test_conditional_branching(engine):
    # Restore real skills in case registry was cleared by other tests
    registry._skills.clear()
    registry._skills.update(_REAL_SKILLS)
    # Register mock volume skill to avoid pycaw dependency
    registry.register(MockVolumeSkill())

    await engine.start()
    wf = Workflow(name="cond_test")

    # Add condition node
    cond = ConditionNode(name="check", condition="context.value > 5")
    wf.add_node(cond)

    # True branch
    true_node = ActionNode(name="high", tool="set_volume", args={"action": "set", "level": 80})
    wf.add_node(true_node)
    wf.add_edge("check", "high", "true")

    # False branch
    false_node = ActionNode(name="low", tool="set_volume", args={"action": "set", "level": 20})
    wf.add_node(false_node)
    wf.add_edge("check", "low", "false")

    wf_task = engine.run_workflow(wf, context={"value": 10})
    wf_id = str(wf_task)
    await wf_task

    status = engine.get_workflow_status(wf_id)
    assert status["status"] == "completed"
    await engine.stop()


@pytest.mark.asyncio
async def test_invalid_edge_reference(engine):
    """Regression test: edge referencing non-existent node should raise ValueError."""
    # Restore real skills in case registry was cleared by other tests
    registry._skills.clear()
    registry._skills.update(_REAL_SKILLS)

    await engine.start()
    wf = Workflow(name="invalid_edge_test")
    node1 = ActionNode(name="step_1", tool="set_volume", args={"action": "set", "level": 10})
    wf.add_node(node1)
    # Reference step_3 which does not exist
    wf.add_edge("step_1", "step_3")

    with pytest.raises(ValueError, match="unknown node"):
        await engine.run_workflow(wf)

    await engine.stop()