"""
Unit tests for Phase 5.3C-A Crash Recovery Foundation.

Tests:
- Orphan task recovery (RUNNING -> PAUSED)
- In-flight step interruption (RUNNING step -> INTERRUPTED)
- Step status preservation (SUCCESS, PENDING, FAILED)
- Session ID preservation
- Single-statement CAS claim atomicity
- Concurrent recovery claim competition (one winner)
- Idempotent recovery (zero duplicate mutations or events)
- Authoritative resume safety check (blocks if INTERRUPTED step present)
- PlanExecutor defense-in-depth guard
"""
import asyncio
import os
import tempfile
import pytest
from datetime import datetime
from uuid import uuid4

from nova.agent.models import (
    TaskRecord,
    TaskStatus,
    ActionStatus,
    TaskStep,
    ExecutionPlan,
    ExecutionContext,
    ToolAction,
    Task,
)
from nova.agent.exceptions import TaskInterruptedStepError
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.executor import PlanExecutor
from nova.events import get_event_bus
from nova.events.events import (
    TaskPausedEvent,
    StepInterruptedEvent,
    TaskResumedEvent,
)


@pytest.fixture
def temp_repo():
    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()
    repo = SQLiteTaskRepository(db_path)
    yield repo
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass


def _create_sample_record(
    task_id: str,
    status: TaskStatus = TaskStatus.RUNNING,
    session_id: str = "test-session-1",
    steps: list = None,
) -> TaskRecord:
    if steps is None:
        steps = [
            TaskStep(step_index=0, tool="tool_a", status=ActionStatus.SUCCESS, result="done"),
            TaskStep(step_index=1, tool="tool_b", status=ActionStatus.RUNNING),
            TaskStep(step_index=2, tool="tool_c", status=ActionStatus.PENDING),
        ]
    plan = ExecutionPlan(steps=[s.to_tool_action() for s in steps])
    context = ExecutionContext(session_id=session_id, execution_id=task_id, task_id=task_id)
    return TaskRecord(
        id=task_id,
        plan=plan,
        context=context,
        status=status,
        steps=steps,
        current_step=1,
    )


# ==============================================================================
# 1. TASK STEP PRIMITIVE
# ==============================================================================

def test_task_step_to_pending():
    step = TaskStep(
        step_index=1,
        tool="test_tool",
        status=ActionStatus.INTERRUPTED,
        error="Previous crash",
        result="partial",
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        retry_count=1,
    )
    step.to_pending()
    assert step.status == ActionStatus.PENDING
    assert step.error is None
    assert step.result is None
    assert step.started_at is None
    assert step.completed_at is None
    assert step.retry_count == 1  # Unchanged by primitive


# ==============================================================================
# 2. RECOVERY STATE MACHINE & STEP STATUS PRESERVATION
# ==============================================================================

@pytest.mark.asyncio
async def test_recover_orphaned_tasks_state_machine(temp_repo):
    service = TaskService(repository=temp_repo)
    task_id = uuid4().hex

    steps = [
        TaskStep(step_index=0, tool="s0_success", status=ActionStatus.SUCCESS, result="res0"),
        TaskStep(step_index=1, tool="s1_running", status=ActionStatus.RUNNING),
        TaskStep(step_index=2, tool="s2_pending", status=ActionStatus.PENDING),
        TaskStep(step_index=3, tool="s3_failed", status=ActionStatus.FAILED, error="prior error"),
    ]
    rec = _create_sample_record(task_id, status=TaskStatus.RUNNING, steps=steps, session_id="session-xyz")
    temp_repo.create(rec)

    recovered = await service.recover_orphaned_tasks()
    assert task_id in recovered

    updated = temp_repo.get(task_id)
    assert updated is not None
    # Task status transition
    assert updated.status == TaskStatus.PAUSED
    assert updated.context.session_id == "session-xyz"

    # Step status transitions
    s0 = updated.steps[0]
    assert s0.status == ActionStatus.SUCCESS
    assert s0.result == "res0"

    s1 = updated.steps[1]
    assert s1.status == ActionStatus.INTERRUPTED
    assert "terminated" in s1.error

    s2 = updated.steps[2]
    assert s2.status == ActionStatus.PENDING

    s3 = updated.steps[3]
    assert s3.status == ActionStatus.FAILED
    assert s3.error == "prior error"


# ==============================================================================
# 3. ATOMICITY & CAS CLAIM
# ==============================================================================

@pytest.mark.asyncio
async def test_cas_claim_and_recover_task_competition(temp_repo):
    task_id = uuid4().hex
    rec = _create_sample_record(task_id, status=TaskStatus.RUNNING)
    temp_repo.create(rec)

    # Process A builds recovery candidate
    candidate_a = temp_repo.get(task_id)
    candidate_a.status = TaskStatus.PAUSED
    candidate_a.steps[1].mark_interrupted("Crashed")

    # Process B builds recovery candidate
    candidate_b = temp_repo.get(task_id)
    candidate_b.status = TaskStatus.PAUSED
    candidate_b.steps[1].mark_interrupted("Crashed")

    # Process A claims first
    won_a = temp_repo.claim_and_recover_task(candidate_a)
    assert won_a is True

    # Process B tries to claim the same task
    won_b = temp_repo.claim_and_recover_task(candidate_b)
    assert won_b is False

    # Confirm final durable state
    final = temp_repo.get(task_id)
    assert final.status == TaskStatus.PAUSED
    assert final.steps[1].status == ActionStatus.INTERRUPTED


# ==============================================================================
# 4. IDEMPOTENCY & SAME-PROCESS SAFETY
# ==============================================================================

@pytest.mark.asyncio
async def test_recover_orphaned_tasks_idempotent(temp_repo):
    service = TaskService(repository=temp_repo)
    task_id = uuid4().hex
    rec = _create_sample_record(task_id, status=TaskStatus.RUNNING)
    temp_repo.create(rec)

    bus = get_event_bus()
    await bus.start()
    events = []

    def listener(event):
        events.append(event)

    unsub_pause = bus.subscribe(TaskPausedEvent, listener)
    unsub_interrupted = bus.subscribe(StepInterruptedEvent, listener)

    try:
        # First recovery
        recovered_1 = await service.recover_orphaned_tasks()
        assert task_id in recovered_1
        await asyncio.sleep(0.05)
        assert len(events) == 2  # StepInterruptedEvent and TaskPausedEvent

        # Second recovery
        events.clear()
        recovered_2 = await service.recover_orphaned_tasks()
        assert recovered_2 == []
        await asyncio.sleep(0.05)
        assert len(events) == 0  # No duplicate events
    finally:
        unsub_pause()
        unsub_interrupted()
        await bus.stop()


@pytest.mark.asyncio
async def test_same_process_active_task_not_recovered(temp_repo):
    service = TaskService(repository=temp_repo)
    task_active = uuid4().hex
    task_orphaned = uuid4().hex

    temp_repo.create(_create_sample_record(task_active, status=TaskStatus.RUNNING))
    temp_repo.create(_create_sample_record(task_orphaned, status=TaskStatus.RUNNING))

    # task_active is currently owned in-memory
    active_ids = {task_active}

    recovered = await service.recover_orphaned_tasks(active_task_ids=active_ids)
    assert task_orphaned in recovered
    assert task_active not in recovered

    # Verify active task remained RUNNING
    active_rec = temp_repo.get(task_active)
    assert active_rec.status == TaskStatus.RUNNING
    assert active_rec.steps[1].status == ActionStatus.RUNNING


# ==============================================================================
# 5. RESUME SAFETY
# ==============================================================================

@pytest.mark.asyncio
async def test_resume_rejected_when_step_interrupted(temp_repo):
    service = TaskService(repository=temp_repo)
    task_id = uuid4().hex

    steps = [
        TaskStep(step_index=0, tool="tool_a", status=ActionStatus.SUCCESS),
        TaskStep(step_index=1, tool="email_sender", status=ActionStatus.INTERRUPTED, error="Crashed"),
    ]
    rec = _create_sample_record(task_id, status=TaskStatus.PAUSED, steps=steps, session_id="sess-1")
    temp_repo.create(rec)

    # Attempt resume: must raise TaskInterruptedStepError
    with pytest.raises(TaskInterruptedStepError) as exc_info:
        await service.resume_task(task_id, session_id="sess-1")

    err = exc_info.value
    assert err.task_id == task_id
    assert err.step_index == 1
    assert err.tool == "email_sender"

    # Database status must still be PAUSED
    unchanged = temp_repo.get(task_id)
    assert unchanged.status == TaskStatus.PAUSED


@pytest.mark.asyncio
async def test_resume_allowed_when_no_interrupted_steps(temp_repo):
    service = TaskService(repository=temp_repo)
    task_id = uuid4().hex

    steps = [
        TaskStep(step_index=0, tool="tool_a", status=ActionStatus.SUCCESS),
        TaskStep(step_index=1, tool="tool_b", status=ActionStatus.PENDING),
    ]
    rec = _create_sample_record(task_id, status=TaskStatus.PAUSED, steps=steps, session_id="sess-1")
    temp_repo.create(rec)

    ctx = await service.resume_task(task_id, session_id="sess-1")
    assert ctx is not None

    resumed = temp_repo.get(task_id)
    assert resumed.status == TaskStatus.RUNNING


# ==============================================================================
# 6. PLANEXECUTOR DEFENSE-IN-DEPTH
# ==============================================================================

@pytest.mark.asyncio
async def test_plan_executor_aborts_on_interrupted_step():
    executor = PlanExecutor()
    task_id = uuid4().hex
    steps = [
        TaskStep(step_index=0, tool="tool_a", status=ActionStatus.SUCCESS, result="ok"),
        TaskStep(step_index=1, tool="unsafe_tool", status=ActionStatus.INTERRUPTED),
        TaskStep(step_index=2, tool="tool_c", status=ActionStatus.PENDING),
    ]
    domain_task = Task(
        id=task_id,
        session_id="sess-1",
        steps=steps,
        status=TaskStatus.RUNNING,
    )

    result = await executor.execute_task_async(domain_task)
    assert result.success is False
    assert "INTERRUPTED" in result.message
    assert "unsafe_tool" in result.message

    # Verify step 1 was NOT executed or mutated to RUNNING
    assert domain_task.steps[1].status == ActionStatus.INTERRUPTED
    assert domain_task.steps[2].status == ActionStatus.PENDING


# ==============================================================================
# 7. P1 / P2 REGRESSION TESTS
# ==============================================================================

@pytest.mark.asyncio
async def test_stale_read_recovery_cannot_overwrite_newer_data(temp_repo):
    """
    P1 REGRESSION TEST:
    Demonstrates that if task data changes while remaining RUNNING after a recovery
    candidate was read, the stale recovery claim MUST NOT overwrite newer data.
    """
    task_id = uuid4().hex
    steps = [
        TaskStep(step_index=0, tool="tool_a", status=ActionStatus.RUNNING),
        TaskStep(step_index=1, tool="tool_b", status=ActionStatus.PENDING),
    ]
    rec = _create_sample_record(task_id, status=TaskStatus.RUNNING, steps=steps, session_id="sess-stale")
    temp_repo.create(rec)

    # 1. Process A reads the candidate with initial updated_at
    candidate_a = temp_repo.get(task_id)
    assert candidate_a is not None
    original_updated_at = candidate_a.updated_at.isoformat()

    # 2. Concurrently, Writer B completes step 0 and starts step 1 while task remains RUNNING
    writer_b_rec = temp_repo.get(task_id)
    writer_b_rec.steps[0].status = ActionStatus.SUCCESS
    writer_b_rec.steps[0].result = "newer legit output from writer B"
    writer_b_rec.steps[1].status = ActionStatus.RUNNING
    writer_b_rec.updated_at = datetime.utcnow()
    temp_repo.update(writer_b_rec)

    # 3. Process A attempts recovery using stale candidate_a and original_updated_at
    candidate_a.steps[0].mark_interrupted("Crashed")
    candidate_a.status = TaskStatus.PAUSED
    candidate_a.updated_at = datetime.utcnow()

    claimed = temp_repo.claim_and_recover_task(candidate_a, expected_updated_at=original_updated_at)

    # 4. Claim MUST fail because persisted state changed
    assert claimed is False

    # 5. Final durable task state MUST remain Writer B's newer state
    final_rec = temp_repo.get(task_id)
    assert final_rec.status == TaskStatus.RUNNING
    assert final_rec.steps[0].status == ActionStatus.SUCCESS
    assert final_rec.steps[0].result == "newer legit output from writer B"
    assert final_rec.steps[1].status == ActionStatus.RUNNING


@pytest.mark.asyncio
async def test_recovery_multiple_running_steps_cardinality(temp_repo):
    """
    P2 REGRESSION TEST:
    If corrupted/unexpected persisted state contains multiple RUNNING steps:
    - ALL RUNNING steps become INTERRUPTED
    - Persisted atomically
    - Emits exactly 1 StepInterruptedEvent for EACH interrupted step
    - Emits exactly 1 TaskPausedEvent
    """
    bus = get_event_bus()
    await bus.start()

    task_id = uuid4().hex
    steps = [
        TaskStep(step_index=0, tool="tool_1", status=ActionStatus.RUNNING),
        TaskStep(step_index=1, tool="tool_2", status=ActionStatus.RUNNING),
        TaskStep(step_index=2, tool="tool_3", status=ActionStatus.RUNNING),
        TaskStep(step_index=3, tool="tool_4", status=ActionStatus.PENDING),
    ]
    rec = _create_sample_record(task_id, status=TaskStatus.RUNNING, steps=steps, session_id="sess-multi")
    temp_repo.create(rec)

    interrupted_events = []
    paused_events = []

    bus.subscribe(StepInterruptedEvent, lambda e: interrupted_events.append(e))
    bus.subscribe(TaskPausedEvent, lambda e: paused_events.append(e))

    service = TaskService(repository=temp_repo)
    recovered_ids = await service.recover_orphaned_tasks()

    assert task_id in recovered_ids
    await asyncio.sleep(0.05)

    # Durable verification
    durable = temp_repo.get(task_id)
    assert durable.status == TaskStatus.PAUSED
    assert durable.steps[0].status == ActionStatus.INTERRUPTED
    assert durable.steps[1].status == ActionStatus.INTERRUPTED
    assert durable.steps[2].status == ActionStatus.INTERRUPTED
    assert durable.steps[3].status == ActionStatus.PENDING

    # Event cardinality verification: 3 StepInterruptedEvents + 1 TaskPausedEvent
    assert len(interrupted_events) == 3
    indices = {e.payload["step_index"] for e in interrupted_events}
    assert indices == {0, 1, 2}
    tools = {e.payload["tool"] for e in interrupted_events}
    assert tools == {"tool_1", "tool_2", "tool_3"}

    assert len(paused_events) == 1
    assert paused_events[0].payload["task_id"] == task_id
    assert paused_events[0].payload["reason"] == "recovered_after_crash"

    await bus.stop()


@pytest.mark.asyncio
async def test_multiple_orchestrator_instances_same_process_safety(temp_repo):
    """
    P2 REGRESSION TEST:
    If Orchestrator A is executing a task in the current process, creating and
    initializing Orchestrator B in the same process MUST NOT treat the task as an orphan.
    """
    from nova.skills.base import BaseSkill
    from nova.skills.registry import registry
    from nova.agent.orchestrator import AgentOrchestrator

    class MultiOrchSkill(BaseSkill):
        def __init__(self):
            self.started_event = asyncio.Event()
            self.proceed_event = asyncio.Event()
            self.executed = False

        @property
        def intent(self) -> str:
            return "multi_orch_skill"

        def can_handle(self, intent_data):
            return intent_data.get("intent") == "multi_orch_skill"

        async def execute(self, intent_data):
            self.executed = True
            self.started_event.set()
            await self.proceed_event.wait()
            return {"status": "ok", "result": "done"}

    skill = MultiOrchSkill()
    registry.register(skill)

    service = TaskService(repository=temp_repo)
    orch_a = AgentOrchestrator(task_service=service)
    await orch_a.initialize()

    task_id = "task-multi-orch-safety"
    plan = ExecutionPlan(steps=[ToolAction(tool="multi_orch_skill", parameters={})])
    ctx = ExecutionContext(session_id="s-orch", execution_id=task_id, task_id=task_id)
    await service.create_task(plan, ctx, session_id="s-orch")

    # Mark PAUSED so request_resume can resume it
    record = await service.get_task(task_id)
    record.status = TaskStatus.PAUSED
    await service.update_task(record)

    # Start executing on Orchestrator A
    resumed = await orch_a.request_resume(task_id, session_id="s-orch")
    assert resumed is True

    # Wait until skill is actively executing
    await skill.started_event.wait()

    # Now create Orchestrator B in the same process and initialize it
    orch_b = AgentOrchestrator(task_service=service)
    await orch_b.initialize()

    # Verify task was NOT recovered as an orphan
    current_db = temp_repo.get(task_id)
    assert current_db.status == TaskStatus.RUNNING
    assert current_db.steps[0].status == ActionStatus.RUNNING

    # Complete execution on Orchestrator A
    skill.proceed_event.set()
    await orch_a._active_executions[task_id]

    # Verify task completed successfully
    final_db = temp_repo.get(task_id)
    assert final_db.status == TaskStatus.COMPLETED
    assert skill.executed is True
