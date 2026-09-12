"""
Unit tests for Task Control Event Ownership and Ordering.
Verifies TaskService sole event publishing, event ordering, and zero duplicate events.
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
)
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
)


class EventTrackingSkill(BaseSkill):
    """Test skill for event tracking."""
    def __init__(self, name: str, should_pause_id: str = None):
        self.tool_name = name
        self.should_pause_id = should_pause_id

    @property
    def intent(self) -> str:
        return self.tool_name

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") == self.tool_name

    async def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        if self.should_pause_id:
            ctrl = get_task_controller(self.should_pause_id)
            if ctrl:
                await ctrl.pause()
        return {"status": "ok", "result": {"detail": f"{self.tool_name} ok"}}


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
async def test_pause_event_ordering(temp_db_path, clean_registry):
    """
    PAUSE order:
    StepCompletedEvent -> TaskPausedEvent
    Step finishes successfully first, then TaskPausedEvent is emitted when safe boundary triggers pause.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    task_id = "t-event-pause"
    s1 = EventTrackingSkill("s1_pause", should_pause_id=task_id)
    s2 = EventTrackingSkill("s2_unreached")
    registry.register(s1)
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="s1_pause", parameters={}),
            ToolAction(tool="s2_unreached", parameters={}),
        ],
        session_id="s1",
    )
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)

    async with capture_task_events() as events:
        res = await orch.execute_with_context(req, ctx)
        await asyncio.sleep(0.05)

        task_events = [e for e in events if getattr(e, "category", "") == "task"]
        event_names = [type(e).__name__ for e in task_events]

        assert event_names == [
            "TaskCreatedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskPausedEvent",
        ]


@pytest.mark.asyncio
async def test_resume_event_ordering(temp_db_path, clean_registry):
    """
    RESUME order:
    TaskResumedEvent -> StepStartedEvent
    Resume transition emits TaskResumedEvent before the resumed step starts.
    """
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    task_id = "t-event-resume"
    s1 = EventTrackingSkill("s1_p", should_pause_id=task_id)
    s2 = EventTrackingSkill("s2_resumed")
    registry.register(s1)
    registry.register(s2)

    orch = AgentOrchestrator(task_service=service)
    await orch.initialize()

    req = ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[
            ToolAction(tool="s1_p", parameters={}),
            ToolAction(tool="s2_resumed", parameters={}),
        ],
        session_id="s1",
    )
    ctx = ExecutionContext(session_id="s1", execution_id=task_id, task_id=task_id)

    async with capture_task_events() as events:
        await orch.execute_with_context(req, ctx)
        await asyncio.sleep(0.05)

        # Clear events to isolate resume phase
        events.clear()

        await orch.resume_task(task_id, session_id="s1")
        await asyncio.sleep(0.05)

        task_events = [e for e in events if getattr(e, "category", "") == "task"]
        event_names = [type(e).__name__ for e in task_events]

        assert event_names == [
            "TaskResumedEvent",
            "StepStartedEvent",
            "StepCompletedEvent",
            "TaskCompletedEvent",
        ]


@pytest.mark.asyncio
async def test_zero_duplicate_events_on_idempotent_cancel(temp_db_path):
    """Zero duplicate events emitted when cancel is called multiple times."""
    repo = SQLiteTaskRepository(temp_db_path)
    service = TaskService(repository=repo)

    plan = ExecutionPlan(steps=[ToolAction(tool="t1", parameters={})])
    ctx = ExecutionContext(session_id="s1", execution_id="t-dup-events", task_id="t-dup-events")

    async with capture_task_events() as events:
        await service.create_task(plan, ctx, session_id="s1")

        await service.cancel_task("t-dup-events", session_id="s1")
        await asyncio.sleep(0.05)

        cancel_events = [e for e in events if isinstance(e, TaskCancelledEvent)]
        assert len(cancel_events) == 1

        # Second cancel
        await service.cancel_task("t-dup-events", session_id="s1")
        await asyncio.sleep(0.05)

        cancel_events_again = [e for e in events if isinstance(e, TaskCancelledEvent)]
        assert len(cancel_events_again) == 1
