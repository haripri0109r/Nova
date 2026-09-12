"""
Unit tests for Task Control Session Isolation.
Verifies cross-session access controls and privacy shielding across all operations.
"""
import pytest
import os
import tempfile
from datetime import datetime

from nova.agent.models import (
    TaskRecord,
    TaskStatus,
    TaskAction,
    TaskCommand,
    ExecutionPlan,
    ExecutionContext,
    ToolAction,
    TaskStep,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.task_resolver import TaskResolver
from nova.agent.task_command_router import TaskCommandRouter
from nova.agent.orchestrator import AgentOrchestrator


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


@pytest.fixture
def temp_router(temp_service):
    orch = AgentOrchestrator(task_service=temp_service)
    resolver = TaskResolver(temp_service)
    return TaskCommandRouter(resolver=resolver, orchestrator=orch, task_service=temp_service)


def _create_record(
    repo,
    task_id: str,
    session_id: str,
    status: TaskStatus = TaskStatus.RUNNING,
    title: str = "Secret Task",
) -> TaskRecord:
    plan = ExecutionPlan(steps=[ToolAction(tool="test_tool", parameters={})])
    ctx = ExecutionContext(session_id=session_id, execution_id=task_id, task_id=task_id)
    record = TaskRecord(
        id=task_id,
        plan=plan,
        context=ctx,
        status=status,
        current_step=0,
        title=title,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        steps=[TaskStep.from_tool_action(plan.steps[0], step_index=0)],
    )
    repo.create(record)
    return record


@pytest.mark.asyncio
async def test_cross_session_pause_blocked(temp_repo, temp_router):
    """User cannot pause another session's task."""
    _create_record(temp_repo, task_id="target-task-1", session_id="owner_session", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="target-task-1", session_id="attacker_session")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "unauthorized"
    assert "not found or access denied" in res.message.lower()


@pytest.mark.asyncio
async def test_cross_session_resume_blocked(temp_repo, temp_router):
    """User cannot resume another session's task."""
    _create_record(temp_repo, task_id="target-task-2", session_id="owner_session", status=TaskStatus.PAUSED)

    cmd = TaskCommand(action=TaskAction.RESUME, task_id="target-task-2", session_id="attacker_session")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "unauthorized"
    assert "not found or access denied" in res.message.lower()


@pytest.mark.asyncio
async def test_cross_session_cancel_blocked(temp_repo, temp_router):
    """User cannot cancel another session's task."""
    _create_record(temp_repo, task_id="target-task-3", session_id="owner_session", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.CANCEL, task_id="target-task-3", session_id="attacker_session")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "unauthorized"
    assert "not found or access denied" in res.message.lower()


@pytest.mark.asyncio
async def test_cross_session_status_blocked(temp_repo, temp_router):
    """User cannot query status of another session's task."""
    _create_record(temp_repo, task_id="target-task-4", session_id="owner_session", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.STATUS, task_id="target-task-4", session_id="attacker_session")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "unauthorized"
    assert "not found or access denied" in res.message.lower()


@pytest.mark.asyncio
async def test_cross_session_list_isolation(temp_repo, temp_router):
    """Listing tasks only returns tasks belonging to caller's session."""
    _create_record(temp_repo, task_id="task-own-1", session_id="user_a", status=TaskStatus.RUNNING)
    _create_record(temp_repo, task_id="task-own-2", session_id="user_a", status=TaskStatus.PAUSED)
    _create_record(temp_repo, task_id="task-foreign", session_id="user_b", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.LIST, session_id="user_a")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.list_dtos is not None
    assert len(res.list_dtos) == 2
    task_ids = [dto.task_id for dto in res.list_dtos]
    assert "task-own-1" in task_ids
    assert "task-own-2" in task_ids
    assert "task-foreign" not in task_ids
