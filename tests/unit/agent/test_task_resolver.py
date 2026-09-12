"""
Unit tests for TaskResolver.
Phase 5.3B deterministic task resolution foundation.
"""
import pytest
import os
import tempfile
from datetime import datetime, timedelta

from nova.agent.models import (
    TaskRecord,
    TaskStatus,
    TaskPriority,
    TaskAction,
    TaskCommand,
    ExecutionPlan,
    ExecutionContext,
    ToolAction,
    TaskStep,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.task_resolver import (
    TaskResolver,
    ResolutionStatus,
    TaskResolutionResult,
)


@pytest.fixture
def temp_repo():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    repo = SQLiteTaskRepository(db_path=path)
    yield repo
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def temp_service(temp_repo):
    return TaskService(repository=temp_repo)


def _create_record(
    repo,
    task_id: str,
    session_id: str = "default",
    status: TaskStatus = TaskStatus.RUNNING,
    title: str = "Test Task",
    updated_at: datetime = None,
) -> TaskRecord:
    now = updated_at or datetime.utcnow()
    plan = ExecutionPlan(steps=[ToolAction(tool="test_tool", parameters={})])
    context = ExecutionContext(session_id=session_id, execution_id=task_id, task_id=task_id)
    steps = [TaskStep.from_tool_action(plan.steps[0], step_index=0)]
    record = TaskRecord(
        id=task_id,
        plan=plan,
        context=context,
        status=status,
        current_step=0,
        title=title,
        created_at=now,
        updated_at=now,
        steps=steps,
    )
    repo.create(record)
    return record


@pytest.mark.asyncio
async def test_exact_id_match_in_session(temp_repo, temp_service):
    """Exact task_id in session resolves with RESOLVED."""
    _create_record(temp_repo, task_id="task-12345", session_id="user1")
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="task-12345", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.task is not None
    assert res.task.id == "task-12345"


@pytest.mark.asyncio
async def test_exact_id_cross_session_unauthorized(temp_repo, temp_service):
    """Exact task_id in different session returns UNAUTHORIZED."""
    _create_record(temp_repo, task_id="task-12345", session_id="user2")
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="task-12345", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.UNAUTHORIZED
    assert res.task is None
    assert "access denied" in res.error_message.lower() or "not found" in res.error_message.lower()


@pytest.mark.asyncio
async def test_prefix_match_in_session(temp_repo, temp_service):
    """Prefix matching with length >= 4 resolves if unique."""
    _create_record(temp_repo, task_id="491c-long-uuid-abc", session_id="user1")
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="491c", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.task is not None
    assert res.task.id == "491c-long-uuid-abc"


@pytest.mark.asyncio
async def test_prefix_match_ambiguous(temp_repo, temp_service):
    """Prefix matching with multiple candidates returns AMBIGUOUS."""
    _create_record(temp_repo, task_id="491c-first", session_id="user1")
    _create_record(temp_repo, task_id="491c-second", session_id="user1")
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="491c", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.AMBIGUOUS
    assert len(res.matching_tasks) == 2
    assert "Ambiguous" in res.error_message


@pytest.mark.asyncio
async def test_prefix_too_short_rejected(temp_repo, temp_service):
    """Prefix shorter than 4 characters is rejected with NOT_FOUND."""
    _create_record(temp_repo, task_id="491c-uuid", session_id="user1")
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="491", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.NOT_FOUND
    assert "at least 4 characters" in res.error_message


@pytest.mark.asyncio
async def test_prefix_cross_session_unauthorized(temp_repo, temp_service):
    """Prefix matching a task in another session returns UNAUTHORIZED."""
    _create_record(temp_repo, task_id="secret-task-xyz", session_id="user2")
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="secret", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.UNAUTHORIZED


@pytest.mark.asyncio
async def test_implicit_pause_single_running(temp_repo, temp_service):
    """Implicit pause with exactly one RUNNING task resolves."""
    _create_record(temp_repo, task_id="task-run-1", session_id="user1", status=TaskStatus.RUNNING)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.task.id == "task-run-1"


@pytest.mark.asyncio
async def test_implicit_pause_multiple_running_ambiguous(temp_repo, temp_service):
    """Implicit pause with multiple RUNNING tasks returns AMBIGUOUS."""
    _create_record(temp_repo, task_id="task-run-1", session_id="user1", status=TaskStatus.RUNNING)
    _create_record(temp_repo, task_id="task-run-2", session_id="user1", status=TaskStatus.RUNNING)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.AMBIGUOUS
    assert len(res.matching_tasks) == 2


@pytest.mark.asyncio
async def test_implicit_pause_zero_running_not_found(temp_repo, temp_service):
    """Implicit pause with no RUNNING tasks returns NOT_FOUND."""
    _create_record(temp_repo, task_id="task-done", session_id="user1", status=TaskStatus.COMPLETED)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.NOT_FOUND


@pytest.mark.asyncio
async def test_implicit_resume_single_paused(temp_repo, temp_service):
    """Implicit resume with exactly one PAUSED task resolves."""
    _create_record(temp_repo, task_id="task-paused", session_id="user1", status=TaskStatus.PAUSED)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.RESUME, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.task.id == "task-paused"


@pytest.mark.asyncio
async def test_implicit_resume_multiple_paused_ambiguous(temp_repo, temp_service):
    """Implicit resume with multiple PAUSED tasks returns AMBIGUOUS."""
    _create_record(temp_repo, task_id="task-p1", session_id="user1", status=TaskStatus.PAUSED)
    _create_record(temp_repo, task_id="task-p2", session_id="user1", status=TaskStatus.PAUSED)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.RESUME, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.AMBIGUOUS
    assert len(res.matching_tasks) == 2


@pytest.mark.asyncio
async def test_implicit_status_zero_active_returns_not_found(temp_repo, temp_service):
    """Implicit status when no task is active returns NOT_FOUND (no silent fallback to completed)."""
    t1 = datetime.utcnow() - timedelta(minutes=5)
    t2 = datetime.utcnow()
    _create_record(temp_repo, task_id="task-old", session_id="user1", status=TaskStatus.COMPLETED, updated_at=t1)
    _create_record(temp_repo, task_id="task-new", session_id="user1", status=TaskStatus.FAILED, updated_at=t2)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.STATUS, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.NOT_FOUND
    assert "No active task found" in res.error_message


@pytest.mark.asyncio
async def test_implicit_status_single_active_resolves(temp_repo, temp_service):
    """Implicit status when exactly one task is active (RUNNING or PAUSED) resolves."""
    _create_record(temp_repo, task_id="task-active", session_id="user1", status=TaskStatus.RUNNING)
    _create_record(temp_repo, task_id="task-done", session_id="user1", status=TaskStatus.COMPLETED)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.STATUS, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.task.id == "task-active"


@pytest.mark.asyncio
async def test_implicit_list_filter(temp_repo, temp_service):
    """List with filter_status returns only matching tasks in session."""
    _create_record(temp_repo, task_id="task-r1", session_id="user1", status=TaskStatus.RUNNING)
    _create_record(temp_repo, task_id="task-p1", session_id="user1", status=TaskStatus.PAUSED)
    _create_record(temp_repo, task_id="task-r2", session_id="user2", status=TaskStatus.RUNNING)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.LIST, filter_status=TaskStatus.RUNNING, session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert len(res.matching_tasks) == 1
    assert res.matching_tasks[0].id == "task-r1"


@pytest.mark.asyncio
async def test_resolver_is_mutation_free(temp_repo, temp_service):
    """Verify TaskResolver does not alter any task data in the repository."""
    record = _create_record(temp_repo, task_id="task-immut", session_id="user1", status=TaskStatus.RUNNING)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="task-immut", session_id="user1")
    res = await resolver.resolve(cmd)
    assert res.status == ResolutionStatus.RESOLVED

    # Re-fetch directly from repository and assert completely untouched
    refetched = temp_repo.get("task-immut")
    assert refetched.status == TaskStatus.RUNNING
    assert refetched.updated_at == record.updated_at


@pytest.mark.asyncio
async def test_resolve_async(temp_repo, temp_service):
    """Verify resolve_async functions properly on an async event loop."""
    _create_record(temp_repo, task_id="task-async", session_id="user1", status=TaskStatus.RUNNING)
    resolver = TaskResolver(temp_service)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="task-async", session_id="user1")
    res = await resolver.resolve_async(cmd)
    assert res.status == ResolutionStatus.RESOLVED
    assert res.task.id == "task-async"
