"""
Unit tests for TaskCommandRouter.
Verifies command dispatch, delegation, formatting, and boundary invariants.
"""
import pytest
import os
import tempfile
from datetime import datetime
from uuid import uuid4

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
    ActionStatus,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.task_resolver import TaskResolver
from nova.agent.task_command_router import (
    TaskCommandRouter,
    TaskCommandResult,
    TaskStatusDTO,
)
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
def temp_resolver(temp_service):
    return TaskResolver(temp_service)


@pytest.fixture
def temp_orchestrator(temp_service):
    orch = AgentOrchestrator(task_service=temp_service)
    return orch


@pytest.fixture
def temp_router(temp_resolver, temp_orchestrator, temp_service):
    return TaskCommandRouter(
        resolver=temp_resolver,
        orchestrator=temp_orchestrator,
        task_service=temp_service,
    )


def _create_record(
    repo,
    task_id: str,
    session_id: str = "default",
    status: TaskStatus = TaskStatus.RUNNING,
    title: str = "Test Task",
    steps_count: int = 3,
    completed_count: int = 1,
) -> TaskRecord:
    plan = ExecutionPlan(steps=[ToolAction(tool=f"tool_{i}", parameters={}) for i in range(steps_count)])
    context = ExecutionContext(session_id=session_id, execution_id=task_id, task_id=task_id)
    steps = []
    for i in range(steps_count):
        step = TaskStep.from_tool_action(plan.steps[i], step_index=i)
        if i < completed_count:
            step.status = ActionStatus.SUCCESS
        elif i == completed_count and status == TaskStatus.RUNNING:
            step.status = ActionStatus.RUNNING
        steps.append(step)

    record = TaskRecord(
        id=task_id,
        plan=plan,
        context=context,
        status=status,
        current_step=completed_count if completed_count < steps_count else steps_count - 1,
        title=title,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        steps=steps,
    )
    repo.create(record)
    return record


@pytest.mark.asyncio
async def test_router_pause_delegation(temp_repo, temp_router, temp_orchestrator):
    """Router delegates PAUSE to orchestrator.pause_task()."""
    _create_record(temp_repo, task_id="task-pause-1", session_id="user1", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="task-pause-1", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.action == TaskAction.PAUSE
    assert res.task_id == "task-pause-1"
    assert "pause requested" in res.message


@pytest.mark.asyncio
async def test_router_resume_delegation(temp_repo, temp_router, temp_orchestrator):
    """Router delegates RESUME to orchestrator.request_resume()."""
    await temp_orchestrator.initialize()
    _create_record(temp_repo, task_id="task-resume-1", session_id="user1", status=TaskStatus.PAUSED)

    cmd = TaskCommand(action=TaskAction.RESUME, task_id="task-resume-1", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.action == TaskAction.RESUME
    assert res.task_id == "task-resume-1"
    assert "resumed" in res.message


@pytest.mark.asyncio
async def test_router_cancel_delegation(temp_repo, temp_router):
    """Router delegates CANCEL to orchestrator.cancel_task()."""
    _create_record(temp_repo, task_id="task-cancel-1", session_id="user1", status=TaskStatus.PAUSED)

    cmd = TaskCommand(action=TaskAction.CANCEL, task_id="task-cancel-1", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.action == TaskAction.CANCEL
    assert res.task_id == "task-cancel-1"
    assert "cancelled" in res.message


@pytest.mark.asyncio
async def test_router_status_formatting(temp_repo, temp_router):
    """Router formats truthful TaskStatusDTO for STATUS query."""
    _create_record(temp_repo, task_id="task-status-1", session_id="user1", status=TaskStatus.RUNNING, steps_count=3, completed_count=2)

    cmd = TaskCommand(action=TaskAction.STATUS, task_id="task-status-1", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.dto is not None
    assert res.dto.task_id == "task-status-1"
    assert res.dto.status == "RUNNING"
    assert res.dto.completed_steps == 2
    assert res.dto.total_steps == 3
    assert "2/3 steps completed" in res.message


@pytest.mark.asyncio
async def test_router_status_truthful_when_pause_pending(temp_repo, temp_router, temp_orchestrator):
    """When pause is pending on in-memory controller, STATUS reports RUNNING (pause requested)."""
    from nova.agent.task_controller import TaskController, register_task_controller
    _create_record(temp_repo, task_id="task-status-pending", session_id="user1", status=TaskStatus.RUNNING, steps_count=2, completed_count=1)

    controller = TaskController("task-status-pending")
    await controller.pause()
    register_task_controller("task-status-pending", controller)

    cmd = TaskCommand(action=TaskAction.STATUS, task_id="task-status-pending", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.dto.pause_pending is True
    assert res.dto.status == "RUNNING (pause requested)"
    assert "RUNNING (pause requested)" in res.message


@pytest.mark.asyncio
async def test_router_list_formatting(temp_repo, temp_router):
    """Router formats task list correctly."""
    _create_record(temp_repo, task_id="task-list-1", session_id="user1", status=TaskStatus.RUNNING)
    _create_record(temp_repo, task_id="task-list-2", session_id="user1", status=TaskStatus.PAUSED)

    cmd = TaskCommand(action=TaskAction.LIST, session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is True
    assert res.list_dtos is not None
    assert len(res.list_dtos) == 2
    assert "Found 2 task(s):" in res.message


@pytest.mark.asyncio
async def test_router_ambiguous_resolution(temp_repo, temp_router):
    """When multiple tasks match, returns ambiguous result with clear error."""
    _create_record(temp_repo, task_id="ambig-1", session_id="user1", status=TaskStatus.RUNNING)
    _create_record(temp_repo, task_id="ambig-2", session_id="user1", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.PAUSE, session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "ambiguous"
    assert "Ambiguous" in res.message or "Multiple" in res.message


@pytest.mark.asyncio
async def test_router_not_found_resolution(temp_router):
    """When task does not exist, returns not_found error."""
    cmd = TaskCommand(action=TaskAction.STATUS, task_id="nonexistent-task", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "not_found"


@pytest.mark.asyncio
async def test_router_unauthorized_privacy_shield(temp_repo, temp_router):
    """Targeting task in foreign session returns privacy-safe error without leaking existence."""
    _create_record(temp_repo, task_id="secret-foreign-task", session_id="other_user", status=TaskStatus.RUNNING)

    cmd = TaskCommand(action=TaskAction.PAUSE, task_id="secret-foreign-task", session_id="user1")
    res = await temp_router.route(cmd)

    assert res.success is False
    assert res.error == "unauthorized"
    assert "not found or access denied" in res.message.lower()


def test_router_no_sqlite_imports():
    """Ensure TaskCommandRouter source has 0 imports of SQLite or TaskRepository."""
    import ast
    import inspect
    from nova.agent import task_command_router
    source = inspect.getsource(task_command_router)
    tree = ast.parse(source)

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module)
            for alias in node.names:
                imported_names.add(alias.name)

    assert "sqlite3" not in imported_names
    assert "TaskRepository" not in imported_names
    assert "SQLiteTaskRepository" not in imported_names
