"""
Phase 5.2A — Live Task Execution Integration Tests.
Covers all 20 required architectural and behavioral test cases:
1. test_task_created_before_execution
2. test_successful_multistep_task
3. test_each_step_persisted_after_completion
4. test_failed_step_marks_task_failed
5. test_pause_prevents_future_step
6. test_cancel_prevents_future_step
7. test_resume_does_not_repeat_successful_steps
8. test_resume_retries_failed_step
9. test_resume_preserves_step_results
10. test_dependencies_respected
11. test_failed_dependency_blocks_dependent_step
12. test_max_steps_failure
13. test_wall_clock_timeout_failure
14. test_task_lifecycle_status_persisted
15. test_success_event_order
16. test_failure_event_order
17. test_cancel_event_order
18. test_pause_resume_event_order
19. test_taskservice_used_by_live_execution
20. test_taskcontroller_changes_execution_behavior
Plus Step 17 strong resume observable side-effects test.
"""
import os
import tempfile
import asyncio
import pytest
from datetime import datetime
from typing import List, Dict, Any
from uuid import uuid4

from nova.agent.models import (
    Task,
    TaskStep,
    TaskRecord,
    TaskStatus,
    TaskPriority,
    ActionStatus,
    ExecutionPlan,
    ExecutionContext,
    ExecutionRequest,
    ExecutionResult,
    ToolAction,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.task_controller import (
    TaskController,
    TaskPaused,
    TaskCancelled,
    get_task_controller,
    register_task_controller,
    remove_task_controller,
)
from nova.agent.executor import PlanExecutor
from nova.agent.orchestrator import AgentOrchestrator
from nova.skills.base import BaseSkill
from nova.skills.registry import registry
from nova.events import get_event_bus
from nova.events.events import (
    BaseEvent,
    TaskCreatedEvent,
    StepStartedEvent,
    StepCompletedEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskCancelledEvent,
    TaskCompletedEvent,
    TaskFailedEvent,
)


class CountingSkill(BaseSkill):
    """Test skill that increments invocation count and can be programmed to succeed or fail."""
    def __init__(self, tool_name: str, should_fail: bool = False, fail_message: str = "fail"):
        self.tool_name = tool_name
        self.should_fail = should_fail
        self.fail_message = fail_message
        self.call_count = 0

    @property
    def intent(self) -> str:
        return self.tool_name

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.tool_name

    async def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        self.call_count += 1
        if self.should_fail:
            return {"status": "error", "message": self.fail_message}
        return {"status": "ok", "result": {"detail": f"{self.tool_name} executed", "count": self.call_count}}


@pytest.fixture
def temp_db_path():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
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


from contextlib import asynccontextmanager


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


# ---------------------------------------------------------------------------
# 1. test_task_created_before_execution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_task_created_before_execution(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)
    skill = CountingSkill("step_1")
    registry.register(skill)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "test_created_before"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[ToolAction(tool="step_1", parameters={})],
        session_id="s1",
    )

    # Before execute, record is not there
    assert await service.get_task(task_id) is None

    result = await orch.execute_with_context(req, ctx)
    assert result.success is True

    record = await service.get_task(task_id)
    assert record is not None
    assert record.id == task_id
    assert record.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# 2. test_successful_multistep_task
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_successful_multistep_task(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)
    s1 = CountingSkill("step_1")
    s2 = CountingSkill("step_2")
    registry.register(s1)
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "multi_success"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="step_1", parameters={}),
            ToolAction(tool="step_2", parameters={}, depends_on=[0]),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is True
    assert s1.call_count == 1
    assert s2.call_count == 1

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.COMPLETED
    assert len(record.steps) == 2
    assert record.steps[0].status == ActionStatus.SUCCESS
    assert record.steps[1].status == ActionStatus.SUCCESS


# ---------------------------------------------------------------------------
# 3. test_each_step_persisted_after_completion
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_each_step_persisted_after_completion(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)
    s1 = CountingSkill("step_1")
    s2 = CountingSkill("step_2")
    registry.register(s1)
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "step_persistence"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="step_1", parameters={}),
            ToolAction(tool="step_2", parameters={}),
        ],
        session_id="s1",
    )

    await orch.execute_with_context(req, ctx)

    record = await service.get_task(task_id)
    assert record.current_step == 1
    assert record.steps[0].result == {"detail": "step_1 executed", "count": 1}
    assert record.steps[1].result == {"detail": "step_2 executed", "count": 1}


# ---------------------------------------------------------------------------
# 4. test_failed_step_marks_task_failed
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_step_marks_task_failed(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)
    s1 = CountingSkill("step_1", should_fail=True, fail_message="step 1 boom")
    s2 = CountingSkill("step_2")
    registry.register(s1)
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "task_failed_mark"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="step_1", parameters={}),
            ToolAction(tool="step_2", parameters={}),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is False
    assert s1.call_count == 1
    assert s2.call_count == 0  # subsequent step does not run

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.FAILED
    assert record.steps[0].status == ActionStatus.FAILED
    assert record.steps[0].error == "step 1 boom"
    assert record.steps[1].status == ActionStatus.PENDING


# ---------------------------------------------------------------------------
# 5. test_pause_prevents_future_step
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pause_prevents_future_step(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)
    
    class PausingSkill(BaseSkill):
        intent = "pause_skill"
        def can_handle(self, d):
            return d.get("intent") == "pause_skill"
        async def execute(self, d):
            ctrl = get_task_controller("task_pause_test")
            if ctrl:
                await ctrl.pause()
            return {"status": "ok", "detail": "paused during step 1"}

    s2 = CountingSkill("step_2")
    registry.register(PausingSkill())
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "task_pause_test"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="pause_skill", parameters={}),
            ToolAction(tool="step_2", parameters={}),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is False
    assert "paused" in result.message.lower()
    assert s2.call_count == 0  # step 2 was prevented

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.PAUSED
    assert record.steps[0].status == ActionStatus.SUCCESS
    assert record.steps[1].status == ActionStatus.PENDING


# ---------------------------------------------------------------------------
# 6. test_cancel_prevents_future_step
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cancel_prevents_future_step(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    class CancellingSkill(BaseSkill):
        intent = "cancel_skill"
        def can_handle(self, d):
            return d.get("intent") == "cancel_skill"
        async def execute(self, d):
            ctrl = get_task_controller("task_cancel_test")
            if ctrl:
                await ctrl.cancel()
            return {"status": "ok", "detail": "cancelled during step 1"}

    s2 = CountingSkill("step_2")
    registry.register(CancellingSkill())
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "task_cancel_test"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="cancel_skill", parameters={}),
            ToolAction(tool="step_2", parameters={}),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is False
    assert "cancelled" in result.message.lower()
    assert s2.call_count == 0  # step 2 prevented

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.CANCELLED
    assert record.steps[0].status == ActionStatus.SUCCESS
    assert record.steps[1].status == ActionStatus.PENDING


# ---------------------------------------------------------------------------
# 7. test_resume_does_not_repeat_successful_steps
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resume_does_not_repeat_successful_steps(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s1 = CountingSkill("step_1")
    s2 = CountingSkill("step_2")
    registry.register(s1)
    registry.register(s2)

    task_id = "resume_no_repeat"
    step1 = TaskStep(step_index=0, tool="step_1", status=ActionStatus.SUCCESS, result={"detail": "done"})
    step2 = TaskStep(step_index=1, tool="step_2", status=ActionStatus.PENDING)
    record = TaskRecord(
        id=task_id,
        plan=ExecutionPlan(steps=[step1.to_tool_action(), step2.to_tool_action()]),
        context=ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id),
        status=TaskStatus.PAUSED,
        current_step=0,
        steps=[step1, step2],
    )
    repo.create(record)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    result = await orch.resume_task(task_id, "s1")
    assert result.success is True
    assert s1.call_count == 0  # Step 1 was NOT executed again!
    assert s2.call_count == 1  # Step 2 executed

    updated = await service.get_task(task_id)
    assert updated.status == TaskStatus.COMPLETED
    assert updated.steps[0].status == ActionStatus.SUCCESS
    assert updated.steps[1].status == ActionStatus.SUCCESS


# ---------------------------------------------------------------------------
# 8. test_resume_retries_failed_step
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resume_retries_failed_step(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s1 = CountingSkill("step_1")
    s2 = CountingSkill("step_2")  # Now works
    registry.register(s1)
    registry.register(s2)

    task_id = "resume_retries_failed"
    step1 = TaskStep(step_index=0, tool="step_1", status=ActionStatus.SUCCESS)
    step2 = TaskStep(step_index=1, tool="step_2", status=ActionStatus.FAILED, error="previous error")
    record = TaskRecord(
        id=task_id,
        plan=ExecutionPlan(steps=[step1.to_tool_action(), step2.to_tool_action()]),
        context=ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id),
        status=TaskStatus.PAUSED,
        current_step=1,
        steps=[step1, step2],
    )
    repo.create(record)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    result = await orch.resume_task(task_id, "s1")
    assert result.success is True
    assert s1.call_count == 0  # skipped
    assert s2.call_count == 1  # retried and succeeded

    updated = await service.get_task(task_id)
    assert updated.status == TaskStatus.COMPLETED
    assert updated.steps[1].status == ActionStatus.SUCCESS


# ---------------------------------------------------------------------------
# 9. test_resume_preserves_step_results
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_resume_preserves_step_results(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s2 = CountingSkill("step_2")
    registry.register(s2)

    task_id = "resume_preserves_results"
    initial_result = {"saved_data": 42}
    step1 = TaskStep(step_index=0, tool="step_1", status=ActionStatus.SUCCESS, result=initial_result)
    step2 = TaskStep(step_index=1, tool="step_2", status=ActionStatus.PENDING)
    record = TaskRecord(
        id=task_id,
        plan=ExecutionPlan(steps=[step1.to_tool_action(), step2.to_tool_action()]),
        context=ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id),
        status=TaskStatus.PAUSED,
        current_step=0,
        steps=[step1, step2],
    )
    repo.create(record)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    result = await orch.resume_task(task_id, "s1")
    assert result.success is True

    updated = await service.get_task(task_id)
    assert updated.steps[0].result == initial_result


# ---------------------------------------------------------------------------
# 10. test_dependencies_respected
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_dependencies_respected(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    execution_order = []

    class OrderSkill(BaseSkill):
        def __init__(self, name):
            self._name = name
        @property
        def intent(self):
            return self._name
        def can_handle(self, d):
            return d.get("intent") == self._name
        async def execute(self, d):
            execution_order.append(self._name)
            return {"status": "ok"}

    registry.register(OrderSkill("A"))
    registry.register(OrderSkill("B"))
    registry.register(OrderSkill("C"))

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "dep_test"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="A", parameters={}),
            ToolAction(tool="B", parameters={}, depends_on=[0]),
            ToolAction(tool="C", parameters={}, depends_on=[1]),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is True
    assert execution_order == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# 11. test_failed_dependency_blocks_dependent_step
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failed_dependency_blocks_dependent_step(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    sA = CountingSkill("A", should_fail=True, fail_message="A broke")
    sB = CountingSkill("B")
    registry.register(sA)
    registry.register(sB)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "dep_fail_blocks"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="A", parameters={}),
            ToolAction(tool="B", parameters={}, depends_on=[0]),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is False
    assert sA.call_count == 1
    assert sB.call_count == 0

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.FAILED
    assert record.steps[1].status == ActionStatus.PENDING


# ---------------------------------------------------------------------------
# 12. test_max_steps_failure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_max_steps_failure(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s1 = CountingSkill("s1")
    s2 = CountingSkill("s2")
    registry.register(s1)
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "max_steps_test"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id, max_steps=1)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="s1", parameters={}),
            ToolAction(tool="s2", parameters={}),
        ],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is False
    assert "Maximum steps" in result.message
    assert s1.call_count == 1
    assert s2.call_count == 0

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# 13. test_wall_clock_timeout_failure
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_wall_clock_timeout_failure(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s1 = CountingSkill("s1")
    registry.register(s1)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "timeout_test"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id, wall_clock_timeout_seconds=0)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[ToolAction(tool="s1", parameters={})],
        session_id="s1",
    )

    result = await orch.execute_with_context(req, ctx)
    assert result.success is False
    assert "timeout" in result.message.lower()

    record = await service.get_task(task_id)
    assert record.status == TaskStatus.FAILED


# ---------------------------------------------------------------------------
# 14. test_task_lifecycle_status_persisted
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_task_lifecycle_status_persisted(temp_db_path, clean_registry):
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s1 = CountingSkill("step_1")
    registry.register(s1)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "lifecycle_persisted"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[ToolAction(tool="step_1", parameters={})],
        session_id="s1",
    )

    await orch.execute_with_context(req, ctx)

    # Re-read fresh from SQLite directly
    fresh_record = repo.get(task_id)
    assert fresh_record is not None
    assert fresh_record.status == TaskStatus.COMPLETED
    assert fresh_record.steps[0].status == ActionStatus.SUCCESS


# ---------------------------------------------------------------------------
# 15. test_success_event_order
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_success_event_order(temp_db_path, clean_registry):
    async with capture_task_events() as event_collector:
        repo = SQLiteTaskRepository(temp_db_path)
        service = TaskService(repository=repo)

        s1 = CountingSkill("step_1")
        registry.register(s1)

        orch = AgentOrchestrator(task_service=service)
        await orch.initialize()

        task_id = "success_events"
        ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
        req = ExecutionRequest(
            requires_execution=True,
            response_text="",
            actions=[ToolAction(tool="step_1", parameters={})],
            session_id="s1",
        )

        await orch.execute_with_context(req, ctx)
        await asyncio.sleep(0.05)

        task_events = [e for e in event_collector if getattr(e, "category", "") == "task"]
        event_names = [type(e).__name__ for e in task_events]

        assert event_names == [
            "TaskCreatedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskCompletedEvent",
        ]


# ---------------------------------------------------------------------------
# 16. test_failure_event_order
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_failure_event_order(temp_db_path, clean_registry):
    async with capture_task_events() as event_collector:
        repo = SQLiteTaskRepository(temp_db_path)
        service = TaskService(repository=repo)

        s1 = CountingSkill("step_1", should_fail=True)
        registry.register(s1)

        orch = AgentOrchestrator(task_service=service)
        await orch.initialize()

        task_id = "failure_events"
        ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
        req = ExecutionRequest(
            requires_execution=True,
            response_text="",
            actions=[ToolAction(tool="step_1", parameters={})],
            session_id="s1",
        )

        await orch.execute_with_context(req, ctx)
        await asyncio.sleep(0.05)

        task_events = [e for e in event_collector if getattr(e, "category", "") == "task"]
        event_names = [type(e).__name__ for e in task_events]

        assert event_names == [
            "TaskCreatedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskFailedEvent",
        ]


# ---------------------------------------------------------------------------
# 17. test_cancel_event_order
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_cancel_event_order(temp_db_path, clean_registry):
    async with capture_task_events() as event_collector:
        repo = SQLiteTaskRepository(temp_db_path)
        service = TaskService(repository=repo)

        class CancellingSkill(BaseSkill):
            intent = "cancel_skill"
            def can_handle(self, d):
                return d.get("intent") == "cancel_skill"
            async def execute(self, d):
                ctrl = get_task_controller("cancel_events")
                if ctrl:
                    await ctrl.cancel()
                return {"status": "ok"}

        s2 = CountingSkill("step_2")
        registry.register(CancellingSkill())
        registry.register(s2)

        orch = AgentOrchestrator(task_service=service)
        await orch.initialize()

        task_id = "cancel_events"
        ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
        req = ExecutionRequest(
            requires_execution=True,
            response_text="",
            actions=[
                ToolAction(tool="cancel_skill", parameters={}),
                ToolAction(tool="step_2", parameters={}),
            ],
            session_id="s1",
        )

        await orch.execute_with_context(req, ctx)
        await asyncio.sleep(0.05)

        task_events = [e for e in event_collector if getattr(e, "category", "") == "task"]
        event_names = [type(e).__name__ for e in task_events]

        assert event_names == [
            "TaskCreatedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskCancelledEvent",
        ]


# ---------------------------------------------------------------------------
# 18. test_pause_resume_event_order
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_pause_resume_event_order(temp_db_path, clean_registry):
    async with capture_task_events() as event_collector:
        repo = SQLiteTaskRepository(temp_db_path)
        service = TaskService(repository=repo)

        class PausingSkill(BaseSkill):
            intent = "pause_skill"
            def can_handle(self, d):
                return d.get("intent") == "pause_skill"
            async def execute(self, d):
                ctrl = get_task_controller("pause_resume_events")
                if ctrl:
                    await ctrl.pause()
                return {"status": "ok"}

        s2 = CountingSkill("step_2")
        registry.register(PausingSkill())
        registry.register(s2)

        orch = AgentOrchestrator(task_service=service)
        await orch.initialize()

        task_id = "pause_resume_events"
        ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
        req = ExecutionRequest(
            requires_execution=True,
            response_text="",
            actions=[
                ToolAction(tool="pause_skill", parameters={}),
                ToolAction(tool="step_2", parameters={}),
            ],
            session_id="s1",
        )

        # Pause execution
        await orch.execute_with_context(req, ctx)

        # Resume execution
        await orch.resume_task(task_id, "s1")
        await asyncio.sleep(0.05)

        task_events = [e for e in event_collector if getattr(e, "category", "") == "task"]
        event_names = [type(e).__name__ for e in task_events]

        assert event_names == [
            "TaskCreatedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskPausedEvent",
            "TaskResumedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskCompletedEvent",
        ]


# ---------------------------------------------------------------------------
# 19. test_taskservice_used_by_live_execution
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_taskservice_used_by_live_execution(temp_db_path, clean_registry):
    """Verify TaskService lifecycle methods are genuinely called and write to SQLite."""
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    s1 = CountingSkill("step_1")
    registry.register(s1)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "live_service_usage"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[ToolAction(tool="step_1", parameters={})],
        session_id="s1",
    )

    await orch.execute_with_context(req, ctx)

    # Check that SQLite record exists and is COMPLETED
    record = repo.get(task_id)
    assert record is not None
    assert record.id == task_id
    assert record.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# 20. test_taskcontroller_changes_execution_behavior
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_taskcontroller_changes_execution_behavior(clean_registry):
    """Prove that controller state directly changes execution behavior at safe boundaries."""
    s1 = CountingSkill("step_1")
    registry.register(s1)

    executor = PlanExecutor()
    ctrl = TaskController("ctrl_behavior_test")
    await ctrl.cancel()

    task = Task(
        id="ctrl_behavior_test",
        session_id="s1",
        steps=[TaskStep(step_index=0, tool="step_1")],
    )

    with pytest.raises(TaskCancelled):
        await executor.execute_task_async(task, controller=ctrl)

    assert s1.call_count == 0  # Cancel stopped execution before step start


# ---------------------------------------------------------------------------
# STEP 17 — STRONG RESUME TEST WITH OBSERVABLE SIDE EFFECTS
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_strong_resume_observable_side_effects(temp_db_path, clean_registry):
    """
    Step A executes once -> SUCCESS
    Step B executes once -> FAILED
    Step C depends on B -> NOT EXECUTED

    Persist.
    Resume with B fixed to succeed.

    Expected:
    A execution count == 1 (never re-executed)
    B execution count == 2 (executed once previously, once now)
    C execution count == 1 (executed once after B succeeds)
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    skill_A = CountingSkill("skill_A", should_fail=False)
    skill_B = CountingSkill("skill_B", should_fail=True)  # Fails on first run
    skill_C = CountingSkill("skill_C", should_fail=False)

    registry.register(skill_A)
    registry.register(skill_B)
    registry.register(skill_C)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    task_id = "strong_resume_test"
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)
    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="skill_A", parameters={}),
            ToolAction(tool="skill_B", parameters={}, depends_on=[0]),
            ToolAction(tool="skill_C", parameters={}, depends_on=[1]),
        ],
        session_id="s1",
    )

    # First run: A succeeds, B fails, C does not execute
    res1 = await orch.execute_with_context(req, ctx)
    assert res1.success is False
    assert skill_A.call_count == 1
    assert skill_B.call_count == 1
    assert skill_C.call_count == 0

    record1 = await service.get_task(task_id)
    assert record1.status == TaskStatus.FAILED
    assert record1.steps[0].status == ActionStatus.SUCCESS
    assert record1.steps[1].status == ActionStatus.FAILED
    assert record1.steps[2].status == ActionStatus.PENDING

    # Fix Skill B so it will succeed on retry
    skill_B.should_fail = False

    # Simulate process pause/resume
    record1.status = TaskStatus.PAUSED
    repo.update(record1)

    # Resume the task
    res2 = await orch.resume_task(task_id, "s1")
    assert res2.success is True

    # VERIFY EXACT CALL COUNTS
    assert skill_A.call_count == 1, f"Expected skill_A to run exactly 1 time, ran {skill_A.call_count}"
    assert skill_B.call_count == 2, f"Expected skill_B to run exactly 2 times, ran {skill_B.call_count}"
    assert skill_C.call_count == 1, f"Expected skill_C to run exactly 1 time, ran {skill_C.call_count}"

    final_record = await service.get_task(task_id)
    assert final_record.status == TaskStatus.COMPLETED
    assert final_record.steps[0].status == ActionStatus.SUCCESS
    assert final_record.steps[1].status == ActionStatus.SUCCESS
    assert final_record.steps[2].status == ActionStatus.SUCCESS
