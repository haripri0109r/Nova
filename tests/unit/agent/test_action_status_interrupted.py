"""
Unit tests for ActionStatus.INTERRUPTED state semantics.
Phase 5.3A foundation.
"""
import pytest
from datetime import datetime

from nova.agent.models import (
    ActionStatus,
    TaskStep,
    ToolAction,
)
from nova.agent.exceptions import InvalidStateTransitionError


def test_action_status_enum_interrupted():
    """Verify ActionStatus contains INTERRUPTED with value 'interrupted'."""
    assert ActionStatus.INTERRUPTED == "interrupted"
    assert ActionStatus("interrupted") == ActionStatus.INTERRUPTED


def test_step_valid_transition_running_to_interrupted():
    """Verify valid transition: PENDING -> RUNNING -> INTERRUPTED."""
    step = TaskStep.from_tool_action(ToolAction(tool="test_tool", parameters={}))
    assert step.status == ActionStatus.PENDING

    step.mark_running()
    assert step.status == ActionStatus.RUNNING

    step.mark_interrupted(error="Process terminated unexpectedly")
    assert step.status == ActionStatus.INTERRUPTED
    assert step.error == "Process terminated unexpectedly"
    assert step.completed_at is not None


def test_step_invalid_transitions_to_interrupted():
    """Verify cannot jump to INTERRUPTED directly from PENDING, SUCCESS, or FAILED."""
    # From PENDING
    step_pending = TaskStep.from_tool_action(ToolAction(tool="test_tool", parameters={}))
    with pytest.raises(InvalidStateTransitionError):
        step_pending.mark_interrupted()

    # From SUCCESS
    step_success = TaskStep.from_tool_action(ToolAction(tool="test_tool", parameters={}))
    step_success.mark_running()
    step_success.mark_success({"output": 1})
    with pytest.raises(InvalidStateTransitionError):
        step_success.mark_interrupted()

    # From FAILED
    step_failed = TaskStep.from_tool_action(ToolAction(tool="test_tool", parameters={}))
    step_failed.mark_running()
    step_failed.mark_failed("Some failure")
    with pytest.raises(InvalidStateTransitionError):
        step_failed.mark_interrupted()


def test_interrupted_step_serialization():
    """Verify TaskStep with INTERRUPTED status roundtrips through JSON cleanly."""
    step = TaskStep.from_tool_action(ToolAction(tool="test_tool", parameters={"foo": "bar"}))
    step.mark_running()
    step.mark_interrupted(error="Crash recovery placeholder")

    data = step.model_dump(mode="json")
    assert data["status"] == "interrupted"
    assert data["error"] == "Crash recovery placeholder"

    restored = TaskStep.model_validate(data)
    assert restored.status == ActionStatus.INTERRUPTED
    assert restored.error == "Crash recovery placeholder"
