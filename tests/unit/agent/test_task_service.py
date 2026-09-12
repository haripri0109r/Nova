"""Unit tests for TaskService sync/async repository contract and lifecycle."""
import os
import tempfile
import pytest
import asyncio
from datetime import datetime

from nova.agent.models import (
    TaskRecord,
    TaskStatus,
    TaskPriority,
    ExecutionContext,
    ExecutionPlan,
    ToolAction,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.events import get_event_bus


@pytest.fixture
def temp_repo():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    repo = SQLiteTaskRepository(db_path)
    yield repo
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.mark.asyncio
async def test_create_and_get_task_no_invalid_await(temp_repo):
    """Verify TaskService calls synchronous repository via to_thread without TypeError."""
    service = TaskService(repository=temp_repo)
    ctx = ExecutionContext(session_id="session-1", execution_id="exec-1")
    plan = ExecutionPlan(steps=[ToolAction(tool="echo", parameters={"msg": "hi"})])

    task_id = await service.create_task(
        plan=plan,
        context=ctx,
        session_id="session-1",
        title="Sample Task",
        description="Verify async contract",
        priority=TaskPriority.HIGH,
    )
    assert task_id == "exec-1"

    # Get task record
    record = await service.get_task(task_id)
    assert record is not None
    assert record.id == task_id
    assert record.title == "Sample Task"
    assert record.description == "Verify async contract"
    assert record.priority == TaskPriority.HIGH
    assert record.status == TaskStatus.RUNNING
    assert len(record.steps) == 1
    assert record.steps[0].tool == "echo"


@pytest.mark.asyncio
async def test_list_tasks(temp_repo):
    service = TaskService(repository=temp_repo)
    ctx1 = ExecutionContext(session_id="s1", execution_id="e1")
    ctx2 = ExecutionContext(session_id="s1", execution_id="e2")
    plan = ExecutionPlan(steps=[])

    await service.create_task(plan, ctx1, "s1")
    await service.create_task(plan, ctx2, "s1")

    all_tasks = await service.list_tasks()
    assert len(all_tasks) == 2

    running_tasks = await service.list_tasks(TaskStatus.RUNNING)
    assert len(running_tasks) == 2


@pytest.mark.asyncio
async def test_pause_and_resume_task(temp_repo):
    service = TaskService(repository=temp_repo)
    ctx = ExecutionContext(session_id="s1", execution_id="e-pr")
    plan = ExecutionPlan(steps=[ToolAction(tool="t1"), ToolAction(tool="t2")])
    task_id = await service.create_task(plan, ctx, "s1")

    # Pause
    paused = await service.pause_task(task_id, "s1")
    assert paused is True

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.PAUSED

    # Resume
    resumed_ctx = await service.resume_task(task_id, "s1")
    assert resumed_ctx is not None
    assert resumed_ctx.session_id == "s1"

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_cancel_task(temp_repo):
    service = TaskService(repository=temp_repo)
    ctx = ExecutionContext(session_id="s1", execution_id="e-cancel")
    plan = ExecutionPlan(steps=[])
    task_id = await service.create_task(plan, ctx, "s1")

    cancelled = await service.cancel_task(task_id, "s1")
    assert cancelled is True

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_complete_and_fail_task(temp_repo):
    service = TaskService(repository=temp_repo)
    ctx1 = ExecutionContext(session_id="s1", execution_id="e-comp")
    plan1 = ExecutionPlan(steps=[])
    task_id1 = await service.create_task(plan1, ctx1, "s1")

    await service.complete_task(task_id1, summary="Done")
    rec1 = await service.get_task(task_id1)
    assert rec1.status == TaskStatus.COMPLETED

    ctx2 = ExecutionContext(session_id="s1", execution_id="e-fail")
    plan2 = ExecutionPlan(steps=[])
    task_id2 = await service.create_task(plan2, ctx2, "s1")

    await service.fail_task(task_id2, error="Fatal crash")
    rec2 = await service.get_task(task_id2)
    assert rec2.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_session_isolation_permission_error(temp_repo):
    service = TaskService(repository=temp_repo)
    ctx = ExecutionContext(session_id="user-a", execution_id="e-sec")
    plan = ExecutionPlan(steps=[])
    task_id = await service.create_task(plan, ctx, "user-a")

    with pytest.raises(PermissionError):
        await service.pause_task(task_id, session_id="user-b")

    with pytest.raises(PermissionError):
        await service.cancel_task(task_id, session_id="user-b")

    with pytest.raises(PermissionError):
        await service.resume_task(task_id, session_id="user-b")
