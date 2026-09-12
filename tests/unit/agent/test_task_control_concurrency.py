"""
Unit tests for Task Control Concurrency and Race Conditions.
Verifies authoritative linearization via TaskService and single execution loop invariants.
"""
import pytest
import os
import tempfile
import asyncio
from datetime import datetime
from typing import Dict, Any, List
from contextlib import asynccontextmanager

from nova.agent.models import (
    Task,
    TaskStep,
    TaskRecord,
    TaskStatus,
    TaskPriority,
    TaskAction,
    TaskCommand,
    ExecutionPlan,
    ExecutionContext,
    ExecutionRequest,
    ToolAction,
    ActionStatus,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.task_controller import (
    TaskController,
    register_task_controller,
    get_task_controller,
    remove_task_controller,
)
from nova.agent.orchestrator import AgentOrchestrator
from nova.skills.base import BaseSkill
from nova.skills.registry import registry
from nova.events import get_event_bus
from nova.events.events import (
    BaseEvent,
    TaskCompletedEvent,
    TaskCancelledEvent,
    TaskPausedEvent,
    TaskResumedEvent,
)


class BlockingSkill(BaseSkill):
    """A skill that signals when it has started and waits on an event before finishing."""
    def __init__(self, name: str):
        self.tool_name = name
        self.started_event = asyncio.Event()
        self.proceed_event = asyncio.Event()
        self.execution_count = 0

    @property
    def intent(self) -> str:
        return self.tool_name

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.tool_name

    async def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        self.execution_count += 1
        self.started_event.set()
        await self.proceed_event.wait()
        return {"status": "ok", "result": {"detail": f"{self.tool_name} completed"}}


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    if os.path.exists(path):
        try:
            os.unlink(path)
        except OSError:
            pass


@pytest.fixture
def clean_registry():
    saved = dict(registry._skills)
    registry._skills.clear()
    yield
    registry._skills.clear()
    registry._skills.update(saved)


@asynccontextmanager
async def capture_task_events():
    bus = get_event_bus()
    await bus.start()
    collected: List[BaseEvent] = []

    def listener(event: BaseEvent):
        collected.append(event)

    unsub = bus.subscribe("*", listener)
    try:
        yield collected
    finally:
        unsub()
        await bus.stop()


@pytest.mark.asyncio
async def test_race_case_a_completion_wins(temp_db_path):
    """
    CASE A: Final completion transition commits first.
    RUNNING -> COMPLETED
    Later/concurrent cancel sees COMPLETED -> cancellation rejected/no-op.
    Final state: COMPLETED.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    plan = ExecutionPlan(steps=[ToolAction(tool="t1", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id="t-case-a", task_id="t-case-a")
    await service.create_task(plan, ctx, session_id="s1", title="Case A")

    # Authoritative completion transition
    await service.complete_task("t-case-a", summary="done")

    record = await service.get_task("t-case-a")
    assert record.status == TaskStatus.COMPLETED

    # Subsequent or concurrent cancel must be rejected
    cancel_success = await service.cancel_task("t-case-a", session_id="s1")
    assert cancel_success is False

    final_record = await service.get_task("t-case-a")
    assert final_record.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_race_case_b_cancellation_wins(temp_db_path):
    """
    CASE B: Cancellation transition commits first.
    RUNNING -> CANCELLED
    Later/concurrent completion attempt sees CANCELLED -> completion rejected.
    Final state: CANCELLED.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    plan = ExecutionPlan(steps=[ToolAction(tool="t1", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id="t-case-b", task_id="t-case-b")
    await service.create_task(plan, ctx, session_id="s1", title="Case B")

    # Authoritative cancellation transition
    cancel_success = await service.cancel_task("t-case-b", session_id="s1")
    assert cancel_success is True

    record = await service.get_task("t-case-b")
    assert record.status == TaskStatus.CANCELLED

    # Subsequent completion attempt must be rejected
    await service.complete_task("t-case-b", summary="done")

    final_record = await service.get_task("t-case-b")
    assert final_record.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_double_cancel_is_idempotent(temp_db_path):
    """
    Double cancel:
    First cancel transitions RUNNING -> CANCELLED.
    Second cancel returns True idempotently and does NOT emit duplicate events.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    plan = ExecutionPlan(steps=[ToolAction(tool="t1", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id="t-dbl-cancel", task_id="t-dbl-cancel")

    async with capture_task_events() as events:
        await service.create_task(plan, ctx, session_id="s1")

        res1 = await service.cancel_task("t-dbl-cancel", session_id="s1")
        assert res1 is True
        await asyncio.sleep(0.05)

        cancel_events_1 = [e for e in events if isinstance(e, TaskCancelledEvent)]
        assert len(cancel_events_1) == 1

        res2 = await service.cancel_task("t-dbl-cancel", session_id="s1")
        assert res2 is True
        await asyncio.sleep(0.05)

        cancel_events_2 = [e for e in events if isinstance(e, TaskCancelledEvent)]
        # Zero duplicate events
        assert len(cancel_events_2) == 1


@pytest.mark.asyncio
async def test_single_execution_loop_guarantee_on_resume(temp_db_path, clean_registry):
    """
    Ensure AgentOrchestrator guarantees AT MOST ONE active execution loop per task.
    Double or rapid repeated resume requests must reject duplicate execution.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    skill = BlockingSkill("block_resume_skill")
    registry.register(skill)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    plan = ExecutionPlan(steps=[ToolAction(tool="block_resume_skill", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id="t-resume-loop", task_id="t-resume-loop")
    await service.create_task(plan, ctx, session_id="s1")

    # Mark PAUSED durably
    record = await service.get_task("t-resume-loop")
    record.status = TaskStatus.PAUSED
    await service.update_task(record)

    # First resume request
    success1 = await orch.request_resume("t-resume-loop", session_id="s1")
    assert success1 is True
    assert "t-resume-loop" in orch._active_executions

    # Wait for skill to start
    await skill.started_event.wait()

    # Second concurrent resume request while first is running
    success2 = await orch.request_resume("t-resume-loop", session_id="s1")
    assert success2 is False  # Rejected because loop is active!

    # Complete skill
    skill.proceed_event.set()
    await orch._active_executions["t-resume-loop"]

    # Loop cleaned up
    assert "t-resume-loop" not in orch._active_executions
    final_record = await service.get_task("t-resume-loop")
    assert final_record.status == TaskStatus.COMPLETED
    assert skill.execution_count == 1


@pytest.mark.asyncio
async def test_cancel_while_step_executing_preserves_step_success(temp_db_path, clean_registry):
    """
    Cancel while a skill is executing:
    Current skill completes and its SUCCESS is persisted.
    PlanExecutor hits safe boundary, raises TaskCancelled.
    Next step does NOT execute.
    Durable status becomes CANCELLED.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    skill1 = BlockingSkill("cancel_step_1")
    skill2 = BlockingSkill("cancel_step_2")
    registry.register(skill1)
    registry.register(skill2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "t-cancel-mid"
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="cancel_step_1", parameters={}),
            ToolAction(tool="cancel_step_2", parameters={}),
        ],
        session_id="s1",
    )
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)

    # Start live execution in background
    exec_task = asyncio.create_task(orch.execute_with_context(req, ctx))

    # Wait for step 1 to start executing
    await skill1.started_event.wait()

    # Cancel task cooperatively
    cancel_requested = await orch.cancel_task(task_id, session_id="s1")
    assert cancel_requested is True

    # Allow step 1 to finish
    skill1.proceed_event.set()

    # Wait for execution task to complete
    result = await exec_task
    assert result.success is False
    assert "cancelled" in result.message.lower()

    # Verify Step 1 is SUCCESS in SQLite, Step 2 was never executed
    record = await service.get_task(task_id)
    assert record.status == TaskStatus.CANCELLED
    assert record.steps[0].status == ActionStatus.SUCCESS
    assert record.steps[1].status == ActionStatus.PENDING
    assert skill1.execution_count == 1
    assert skill2.execution_count == 0


@pytest.mark.asyncio
async def test_pause_vs_completion_race(temp_db_path):
    """
    If completion commits first, pause is rejected.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    plan = ExecutionPlan(steps=[ToolAction(tool="t1", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id="t-pause-race", task_id="t-pause-race")
    await service.create_task(plan, ctx, session_id="s1")

    await service.complete_task("t-pause-race", summary="done")

    # Pause must be rejected because task is already completed
    pause_success = await service.pause_task("t-pause-race", session_id="s1")
    assert pause_success is False

    record = await service.get_task("t-pause-race")
    assert record.status == TaskStatus.COMPLETED
