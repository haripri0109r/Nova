"""
Unit tests for Task Execution Uniqueness.
Verifies that AgentOrchestrator guarantees AT MOST ONE active background execution loop per task.
"""
import pytest
import os
import tempfile
import asyncio
from typing import Dict, Any

from nova.agent.models import (
    TaskStatus,
    ExecutionPlan,
    ExecutionContext,
    ToolAction,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.orchestrator import AgentOrchestrator
from nova.skills.base import BaseSkill
from nova.skills.registry import registry


class UniquenessSkill(BaseSkill):
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
        return {"status": "ok", "result": {"detail": "uniqueness pass"}}


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


@pytest.mark.asyncio
async def test_single_execution_loop_guarantee_standalone(temp_db_path, clean_registry):
    """
    Ensure AgentOrchestrator guarantees AT MOST ONE active execution loop per task.
    Concurrent or rapid repeated resume requests must reject duplicate execution.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    skill = UniquenessSkill("unique_skill")
    registry.register(skill)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "t-unique-loop"
    plan = ExecutionPlan(steps=[ToolAction(tool="unique_skill", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    await service.create_task(plan, ctx, session_id="s1")

    # Mark PAUSED durably
    record = await service.get_task(task_id)
    record.status = TaskStatus.PAUSED
    await service.update_task(record)

    # First resume request
    success1 = await orch.request_resume(task_id, session_id="s1")
    assert success1 is True
    assert task_id in orch._active_executions

    # Wait for skill to start
    await skill.started_event.wait()

    # Second concurrent resume request while first is running
    success2 = await orch.request_resume(task_id, session_id="s1")
    assert success2 is False  # Rejected because loop is active!

    # Complete skill
    skill.proceed_event.set()
    await orch._active_executions[task_id]

    # Loop cleaned up
    assert task_id not in orch._active_executions
    final_record = await service.get_task(task_id)
    assert final_record.status == TaskStatus.COMPLETED
    assert skill.execution_count == 1
