"""
Unit tests for workflow data models.
"""
import pytest
from nova.workflows import Workflow, Node, ActionNode, ConditionNode, ParallelNode


def test_workflow_creation():
    wf = Workflow(name="test_workflow", description="Test workflow")
    assert wf.id
    assert wf.name == "test_workflow"
    assert wf.status == "pending"
    assert wf.nodes == []
    assert wf.edges == []


def test_workflow_add_node():
    wf = Workflow(name="test")
    from nova.workflows.nodes import ActionNode
    node = ActionNode(name="test_action", tool="test_tool", args={})
    wf.add_node(node)
    assert len(wf.nodes) == 1
    assert wf.nodes[0].name == "test_action"


def test_workflow_add_edge():
    wf = Workflow(name="test")
    wf.add_edge("node1", "node2")
    assert len(wf.edges) == 1
    assert wf.edges[0].from_node == "node1"
    assert wf.edges[0].to_node == "node2"


def test_action_node_creation():
    from nova.workflows.nodes import ActionNode
    node = ActionNode(name="test", tool="tool_name", args={"key": "value"})
    assert node.id
    assert node.name == "test"
    assert node.tool == "tool_name"
    assert node.args == {"key": "value"}
    assert node.status == "pending"


def test_condition_node_creation():
    from nova.workflows.nodes import ConditionNode
    node = ConditionNode(name="cond", condition="context.value > 5")
    assert node.condition == "context.value > 5"


def test_parallel_node_creation():
    from nova.workflows.nodes import ParallelNode
    from nova.workflows.nodes import ActionNode
    child1 = ActionNode(name="a", tool="a")
    child2 = ActionNode(name="b", tool="b")
    parallel = ParallelNode(name="parallel", children=[child1, child2])
    assert len(parallel.children) == 2