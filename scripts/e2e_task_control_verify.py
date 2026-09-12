"""
End-to-End Live Task Control, Status, List, and Session Verification for Nova Phase 5.3B.
Verifies real pause, resume, cancel, status, list, and session isolation using the real Nova runtime.
"""
import asyncio
import os
import sys
import tempfile
from typing import List

# Ensure src is at the very front of sys.path so 'import nova' points to src/nova
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import nova.skills
from nova.events import get_event_bus
from nova.events.events import (
    TaskCreatedEvent,
    StepStartedEvent,
    StepCompletedEvent,
    TaskPausedEvent,
    TaskResumedEvent,
    TaskCancelledEvent,
    TaskCompletedEvent,
)
from nova.agent.task_repository import SQLiteTaskRepository
from nova.agent.task_service import TaskService
from nova.agent.orchestrator import get_agent_orchestrator
from nova.agent.task_resolver import TaskResolver
from nova.agent.task_command_router import TaskCommandRouter
from nova.agent.models import (
    TaskAction,
    TaskCommand,
    TaskPriority,
    TaskStatus,
    ActionStatus,
    ExecutionContext,
    ExecutionRequest,
    ExecutionPlan,
    ToolAction,
)


async def run_e2e_verification():
    print("=" * 70)
    print("NOVA PHASE 5.3B E2E VERIFICATION: LIVE CONTROL + STATUS + LIST + ISOLATION")
    print("=" * 70)

    db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    db_path = db_file.name
    db_file.close()

    bus = get_event_bus()
    await bus.start()

    captured_events: List[any] = []

    def event_collector(event):
        captured_events.append(event)

    bus.subscribe(TaskCreatedEvent, event_collector)
    bus.subscribe(StepStartedEvent, event_collector)
    bus.subscribe(StepCompletedEvent, event_collector)
    bus.subscribe(TaskPausedEvent, event_collector)
    bus.subscribe(TaskResumedEvent, event_collector)
    bus.subscribe(TaskCancelledEvent, event_collector)
    bus.subscribe(TaskCompletedEvent, event_collector)

    try:
        repo = SQLiteTaskRepository(db_path)
        task_service = TaskService(repository=repo)
        orchestrator = get_agent_orchestrator()
        orchestrator._task_service = task_service
        resolver = TaskResolver(task_service=task_service)
        router = TaskCommandRouter(
            task_service=task_service,
            orchestrator=orchestrator,
            resolver=resolver,
        )

        # -------------------------------------------------------------
        # SCENARIO 1: Real Multi-Step Task -> Pause -> Resume -> Complete
        # -------------------------------------------------------------
        print("\n--- SCENARIO 1: Live Multi-Step Execution -> Pause -> Resume -> Complete ---")
        task_id_1 = "task-e2e-live-1"
        req1 = ExecutionRequest(
            requires_execution=True,
            response_text="Multi-step test",
            actions=[
                ToolAction(tool="find_file", parameters={"pattern": "nonexistent_e2e_search_pattern_12345"}, description="Deep search 1"),
                ToolAction(tool="find_file", parameters={"pattern": "py"}, description="Find python files"),
                ToolAction(tool="find_file", parameters={"pattern": "md"}, description="Find markdown files"),
            ],
            session_id="session-user-1",
        )
        ctx1 = ExecutionContext(
            session_id="session-user-1",
            execution_id=task_id_1,
            task_id=task_id_1,
        )

        # Start execution in background
        exec_task = asyncio.create_task(orchestrator.execute_with_context(req1, ctx1))

        # Wait briefly for step 0 to start executing
        await asyncio.sleep(0.05)

        print("Issuing PAUSE command via TaskCommandRouter...")
        pause_cmd = TaskCommand(action=TaskAction.PAUSE, task_id=task_id_1, session_id="session-user-1")
        pause_res = await router.route(pause_cmd)
        print(f"Pause response: success={pause_res.success}, message='{pause_res.message}'")
        assert pause_res.success is True

        # Query STATUS while pause is executing / completing active step
        status_cmd = TaskCommand(action=TaskAction.STATUS, task_id=task_id_1, session_id="session-user-1")
        status_res = await router.route(status_cmd)
        print(f"Status response during pause: '{status_res.message}'")
        assert "pause requested" in status_res.message

        # Wait for the background execution to hit the pause boundary
        await exec_task

        # Verify durable status is PAUSED
        db_task1 = await task_service.get_task(task_id_1)
        print(f"Durable state after pause: status={db_task1.status.value}")
        assert db_task1.status == TaskStatus.PAUSED
        assert db_task1.steps[0].status == ActionStatus.SUCCESS
        assert db_task1.steps[1].status == ActionStatus.PENDING
        assert db_task1.steps[2].status == ActionStatus.PENDING
        print("[OK] Step 1 finished safely and steps 2-3 remained pending on pause boundary.")

        # Now issue RESUME
        print("\nIssuing RESUME command via TaskCommandRouter...")
        resume_cmd = TaskCommand(action=TaskAction.RESUME, task_id=task_id_1, session_id="session-user-1")
        resume_res = await router.route(resume_cmd)
        print(f"Resume response: success={resume_res.success}, message='{resume_res.message}'")
        assert resume_res.success is True

        # Wait for resumed execution to finish
        while task_id_1 in orchestrator._active_executions:
            await asyncio.sleep(0.05)

        db_task1_resumed = await task_service.get_task(task_id_1)
        print(f"Durable state after resume completion: status={db_task1_resumed.status.value}")
        assert db_task1_resumed.status == TaskStatus.COMPLETED
        for idx, s in enumerate(db_task1_resumed.steps):
            print(f"  Step {idx} ({s.description}): {s.status.value}")
            assert s.status == ActionStatus.SUCCESS
        print("[OK] All steps completed successfully after resume!")

        # -------------------------------------------------------------
        # SCENARIO 2: Cancel Flow
        # -------------------------------------------------------------
        print("\n--- SCENARIO 2: Live Cancel & Idempotent Re-Cancel ---")
        task_id_2 = "task-e2e-cancel-2"
        plan2 = ExecutionPlan(steps=[
            ToolAction(tool="find_file", parameters={"pattern": "test1"}, description="Cancel step 1"),
            ToolAction(tool="find_file", parameters={"pattern": "test2"}, description="Cancel step 2"),
        ])
        ctx2 = ExecutionContext(session_id="session-user-1", execution_id=task_id_2, task_id=task_id_2)
        await task_service.create_task(plan2, ctx2, session_id="session-user-1", title="Cancel Test Task")
        await task_service.pause_task(task_id_2, session_id="session-user-1")

        cancel_cmd = TaskCommand(action=TaskAction.CANCEL, task_id=task_id_2, session_id="session-user-1")
        cancel_res = await router.route(cancel_cmd)
        print(f"Cancel response: success={cancel_res.success}, message='{cancel_res.message}'")
        assert cancel_res.success is True

        db_task2 = await task_service.get_task(task_id_2)
        assert db_task2.status == TaskStatus.CANCELLED
        print(f"Task 2 durable state: {db_task2.status.value}")

        # Idempotent cancel
        cancel_res_again = await router.route(cancel_cmd)
        print(f"Idempotent cancel response: success={cancel_res_again.success}, message='{cancel_res_again.message}'")
        assert cancel_res_again.success is True
        assert "already cancelled" in cancel_res_again.message.lower()
        print("[OK] Cancel and idempotent re-cancel verified.")

        # -------------------------------------------------------------
        # SCENARIO 3: Session Isolation & Privacy Shield
        # -------------------------------------------------------------
        print("\n--- SCENARIO 3: Session Isolation & Privacy Shield ---")
        # User in session 2 attempts to query or control session 1 task
        foreign_status_cmd = TaskCommand(
            action=TaskAction.STATUS,
            task_id=task_id_1,
            session_id="session-user-2-unauthorized",
        )
        foreign_res = await router.route(foreign_status_cmd)
        print(f"Foreign session status response: success={foreign_res.success}, message='{foreign_res.message}'")
        assert foreign_res.success is False
        assert "not found or access denied" in foreign_res.message

        foreign_pause_cmd = TaskCommand(
            action=TaskAction.PAUSE,
            task_id=task_id_1,
            session_id="session-user-2-unauthorized",
        )
        foreign_pause_res = await router.route(foreign_pause_cmd)
        print(f"Foreign session pause response: success={foreign_pause_res.success}, message='{foreign_pause_res.message}'")
        assert foreign_pause_res.success is False
        assert "not found or access denied" in foreign_pause_res.message

        # List tasks for session-user-2 should NOT leak session 1 tasks
        list_cmd = TaskCommand(action=TaskAction.LIST, session_id="session-user-2-unauthorized")
        list_res = await router.route(list_cmd)
        print(f"List response for session 2: '{list_res.message}'")
        assert "no tasks found" in list_res.message.lower()

        # List tasks for session-user-1 should show session 1 tasks
        list_user1_cmd = TaskCommand(action=TaskAction.LIST, session_id="session-user-1")
        list_user1_res = await router.route(list_user1_cmd)
        print(f"List response for session 1:\n{list_user1_res.message}")
        assert task_id_1 in list_user1_res.message
        assert task_id_2 in list_user1_res.message
        print("[OK] Session isolation and privacy shield strictly verified.")

        # -------------------------------------------------------------
        # SCENARIO 4: Event Bus Verification & Sequence
        # -------------------------------------------------------------
        print("\n--- SCENARIO 4: Lifecycle Event Bus Verification ---")
        event_names = [type(e).__name__ for e in captured_events]
        print(f"Captured {len(captured_events)} events: {event_names}")
        assert "TaskPausedEvent" in event_names
        assert "TaskResumedEvent" in event_names
        assert "TaskCancelledEvent" in event_names
        assert "TaskCompletedEvent" in event_names

        # Verify ordering for Task 1:
        # StepCompletedEvent (step 1) -> TaskPausedEvent -> TaskResumedEvent -> StepStartedEvent (step 2) -> TaskCompletedEvent
        t1_events = [
            e for e in captured_events
            if getattr(e, "task_id", None) == task_id_1
            or (hasattr(e, "payload") and isinstance(e.payload, dict) and e.payload.get("task_id") == task_id_1)
        ]
        t1_names = [type(e).__name__ for e in t1_events]
        print(f"Task 1 specific events: {t1_names}")

        pause_idx = t1_names.index("TaskPausedEvent")
        resume_idx = t1_names.index("TaskResumedEvent")
        complete_idx = t1_names.index("TaskCompletedEvent")
        assert pause_idx < resume_idx < complete_idx
        print("[OK] Event sequence verified: Pause -> Resume -> Complete.")

        print("\n" + "=" * 70)
        print("ALL E2E TASK CONTROL SCENARIOS SUCCESSFULLY VERIFIED!")
        print("=" * 70)

    finally:
        await bus.stop()
        if os.path.exists(db_path):
            try:
                os.unlink(db_path)
            except OSError:
                pass


if __name__ == "__main__":
    asyncio.run(run_e2e_verification())
