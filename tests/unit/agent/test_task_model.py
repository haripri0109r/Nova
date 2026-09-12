"""Unit tests for the canonical Task domain model and lifecycle."""
import pytest
from datetime import datetime

from nova.agent.models import (
    ActionStatus,
    TaskStatus,
    TaskPriority,
    TaskStep,
    Task,
    TaskRecord,
    ToolAction,
    ExecutionPlan,
    ExecutionContext,
)
from nova.agent.exceptions import InvalidStateTransitionError, AgentError


class TestTaskStatus:
    def test_status_values(self):
        assert TaskStatus.PENDING == "pending"
        assert TaskStatus.RUNNING == "running"
        assert TaskStatus.PAUSED == "paused"
        assert TaskStatus.CANCELLED == "cancelled"
        assert TaskStatus.COMPLETED == "completed"
        assert TaskStatus.FAILED == "failed"

    def test_is_terminal(self):
        assert TaskStatus.COMPLETED.is_terminal() is True
        assert TaskStatus.FAILED.is_terminal() is True
        assert TaskStatus.CANCELLED.is_terminal() is True
        assert TaskStatus.PENDING.is_terminal() is False
        assert TaskStatus.RUNNING.is_terminal() is False
        assert TaskStatus.PAUSED.is_terminal() is False

    def test_is_active(self):
        assert TaskStatus.PENDING.is_active() is True
        assert TaskStatus.RUNNING.is_active() is True
        assert TaskStatus.PAUSED.is_active() is True
        assert TaskStatus.COMPLETED.is_active() is False
        assert TaskStatus.FAILED.is_active() is False
        assert TaskStatus.CANCELLED.is_active() is False

    def test_valid_transitions(self):
        # Self-transitions are valid
        for status in TaskStatus:
            assert status.can_transition_to(status) is True

        # PENDING transitions
        assert TaskStatus.PENDING.can_transition_to(TaskStatus.RUNNING) is True
        assert TaskStatus.PENDING.can_transition_to(TaskStatus.CANCELLED) is True
        assert TaskStatus.PENDING.can_transition_to(TaskStatus.PAUSED) is False
        assert TaskStatus.PENDING.can_transition_to(TaskStatus.COMPLETED) is False
        assert TaskStatus.PENDING.can_transition_to(TaskStatus.FAILED) is False

        # RUNNING transitions
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.PAUSED) is True
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.COMPLETED) is True
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.FAILED) is True
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.CANCELLED) is True
        assert TaskStatus.RUNNING.can_transition_to(TaskStatus.PENDING) is False

        # PAUSED transitions
        assert TaskStatus.PAUSED.can_transition_to(TaskStatus.RUNNING) is True
        assert TaskStatus.PAUSED.can_transition_to(TaskStatus.CANCELLED) is True
        assert TaskStatus.PAUSED.can_transition_to(TaskStatus.COMPLETED) is False
        assert TaskStatus.PAUSED.can_transition_to(TaskStatus.FAILED) is False

        # Terminal transitions (cannot transition out)
        for term in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
            for target in TaskStatus:
                if target != term:
                    assert term.can_transition_to(target) is False


class TestTaskPriority:
    def test_priority_levels(self):
        assert TaskPriority.LOW.level == 1
        assert TaskPriority.NORMAL.level == 2
        assert TaskPriority.HIGH.level == 3
        assert TaskPriority.URGENT.level == 4

    def test_priority_comparisons(self):
        assert TaskPriority.LOW < TaskPriority.NORMAL
        assert TaskPriority.NORMAL < TaskPriority.HIGH
        assert TaskPriority.HIGH < TaskPriority.URGENT

        assert TaskPriority.URGENT > TaskPriority.HIGH
        assert TaskPriority.NORMAL <= TaskPriority.NORMAL
        assert TaskPriority.HIGH >= TaskPriority.NORMAL

    def test_priority_string_equality(self):
        assert TaskPriority.NORMAL == "normal"
        assert TaskPriority.HIGH == "high"


class TestTaskStep:
    def test_step_defaults(self):
        step = TaskStep(tool="test_tool")
        assert step.step_id is not None
        assert step.tool == "test_tool"
        assert step.status == ActionStatus.PENDING
        assert step.parameters == {}
        assert step.depends_on == []
        assert step.result is None
        assert step.error is None
        assert step.started_at is None
        assert step.completed_at is None

    def test_mark_running(self):
        step = TaskStep(tool="test_tool")
        step.mark_running()
        assert step.status == ActionStatus.RUNNING
        assert isinstance(step.started_at, datetime)

    def test_mark_success(self):
        step = TaskStep(tool="test_tool")
        step.mark_running()
        step.mark_success(result={"data": 123}, execution_time_ms=45)
        assert step.status == ActionStatus.SUCCESS
        assert step.result == {"data": 123}
        assert step.execution_time_ms == 45
        assert isinstance(step.completed_at, datetime)

    def test_mark_failed(self):
        step = TaskStep(tool="test_tool")
        step.mark_running()
        step.mark_failed(error="Timeout", execution_time_ms=100)
        assert step.status == ActionStatus.FAILED
        assert step.error == "Timeout"
        assert step.execution_time_ms == 100
        assert isinstance(step.completed_at, datetime)

    def test_mark_skipped(self):
        step = TaskStep(tool="test_tool")
        step.mark_skipped(reason="Condition not met")
        assert step.status == ActionStatus.SKIPPED
        assert step.error == "Condition not met"
        assert isinstance(step.completed_at, datetime)

    def test_tool_action_interop(self):
        action = ToolAction(tool="search", parameters={"query": "nova"}, description="Search query")
        step = TaskStep.from_tool_action(action, step_index=2)
        assert step.tool == "search"
        assert step.parameters == {"query": "nova"}
        assert step.description == "Search query"
        assert step.step_index == 2

        roundtrip_action = step.to_tool_action()
        assert roundtrip_action.tool == "search"
        assert roundtrip_action.parameters == {"query": "nova"}
        assert roundtrip_action.description == "Search query"


class TestTask:
    def test_task_creation_defaults(self):
        task = Task(session_id="sess-1", title="Build Nova")
        assert task.session_id == "sess-1"
        assert task.title == "Build Nova"
        assert task.status == TaskStatus.PENDING
        assert task.priority == TaskPriority.NORMAL
        assert task.steps == []
        assert task.current_step_index == -1
        assert task.started_at is None
        assert task.completed_at is None
        assert isinstance(task.created_at, datetime)
        assert isinstance(task.updated_at, datetime)

    def test_task_steps_management(self):
        task = Task(session_id="sess-1")
        step1 = TaskStep(tool="tool_a", step_index=0)
        step2 = TaskStep(tool="tool_b")
        task.add_step(step1)
        task.add_step(step2)

        assert len(task.steps) == 2
        assert task.steps[0].tool == "tool_a"
        assert task.steps[1].tool == "tool_b"
        assert task.steps[1].step_index == 1

        task.current_step_index = 0
        assert task.current_step == step1
        task.current_step_index = 1
        assert task.current_step == step2
        task.current_step_index = 99
        assert task.current_step is None

    def test_valid_lifecycle_flow(self):
        task = Task(session_id="sess-1")
        assert task.status == TaskStatus.PENDING

        # start
        task.start()
        assert task.status == TaskStatus.RUNNING
        assert task.started_at is not None

        # pause
        task.pause()
        assert task.status == TaskStatus.PAUSED

        # resume
        task.resume()
        assert task.status == TaskStatus.RUNNING

        # complete
        task.complete()
        assert task.status == TaskStatus.COMPLETED
        assert task.completed_at is not None
        assert task.status.is_terminal() is True

    def test_fail_transition(self):
        task = Task(session_id="sess-1")
        task.start()
        task.fail(error="Network unreachable")
        assert task.status == TaskStatus.FAILED
        assert task.error == "Network unreachable"
        assert task.completed_at is not None

    def test_cancel_transition(self):
        task = Task(session_id="sess-1")
        task.cancel(reason="User cancelled")
        assert task.status == TaskStatus.CANCELLED
        assert task.metadata.get("cancel_reason") == "User cancelled"
        assert task.completed_at is not None

    def test_invalid_state_transition_raises(self):
        task = Task(session_id="sess-1")
        assert task.status == TaskStatus.PENDING

        # PENDING -> COMPLETED is invalid
        with pytest.raises(InvalidStateTransitionError) as exc_info:
            task.complete()
        assert "Invalid state transition from 'pending' to 'completed'" in str(exc_info.value)
        assert isinstance(exc_info.value, AgentError)
        assert isinstance(exc_info.value, ValueError)

        # Start and complete task
        task.start()
        task.complete()

        # Terminal state -> any transition is invalid
        with pytest.raises(InvalidStateTransitionError):
            task.resume()

    def test_task_to_record_roundtrip(self):
        task = Task(
            id="t-123",
            session_id="sess-99",
            title="Deploy App",
            description="Production deployment",
            priority=TaskPriority.HIGH,
            max_steps=10,
            wall_clock_timeout_seconds=600,
            metadata={"env": "prod"},
        )
        task.add_step(TaskStep(tool="git_clone", parameters={"url": "example.com"}))
        task.add_step(TaskStep(tool="run_build", parameters={"target": "prod"}))
        task.steps[0].mark_running()
        task.steps[0].mark_success(result={"commit": "abc1234"}, execution_time_ms=50)

        record = task.to_record()
        assert isinstance(record, TaskRecord)
        assert record.id == "t-123"
        assert record.title == "Deploy App"
        assert record.description == "Production deployment"
        assert record.priority == TaskPriority.HIGH
        assert record.context.session_id == "sess-99"
        assert record.status == TaskStatus.PENDING
        assert record.max_steps == 10
        assert record.wall_clock_timeout_seconds == 600
        assert record.metadata == {"env": "prod"}
        assert len(record.plan.steps) == 2
        assert len(record.steps) == 2
        assert record.steps[0].status == ActionStatus.SUCCESS
        assert record.steps[0].result == {"commit": "abc1234"}

        # Convert back
        restored = record.to_task()
        assert restored.id == "t-123"
        assert restored.session_id == "sess-99"
        assert restored.title == "Deploy App"
        assert restored.description == "Production deployment"
        assert restored.priority == TaskPriority.HIGH
        assert restored.status == TaskStatus.PENDING
        assert restored.max_steps == 10
        assert restored.wall_clock_timeout_seconds == 600
        assert restored.metadata == {"env": "prod"}
        assert len(restored.steps) == 2
        assert restored.steps[0].tool == "git_clone"
        assert restored.steps[0].status == ActionStatus.SUCCESS
        assert restored.steps[0].result == {"commit": "abc1234"}
        assert restored.steps[1].tool == "run_build"
        assert restored.steps[1].status == ActionStatus.PENDING

    def test_plan_and_steps_synchronization(self):
        plan = ExecutionPlan(steps=[ToolAction(tool="initial", parameters={})])
        task = Task(session_id="sess-1", plan=plan)
        task.add_step(TaskStep(tool="step_1"))
        task.add_step(TaskStep(tool="step_2"))

        assert len(task.steps) == 2
        assert len(task.plan.steps) == 2
        assert task.plan.steps[0].tool == "step_1"
        assert task.plan.steps[1].tool == "step_2"

    def test_retry_cleanup_failed_then_success(self):
        step = TaskStep(tool="flaky_api")
        step.mark_running()
        step.mark_failed(error="Connection refused", execution_time_ms=10)
        assert step.status == ActionStatus.FAILED
        assert step.error == "Connection refused"
        assert step.result is None
        assert step.completed_at is not None

        # Retry
        step.retry_count += 1
        step.mark_running()
        assert step.status == ActionStatus.RUNNING
        assert step.completed_at is None

        step.mark_success(result={"data": "ok"}, execution_time_ms=25)
        assert step.status == ActionStatus.SUCCESS
        assert step.result == {"data": "ok"}
        assert step.error is None  # Stale error must be cleared
        assert step.retry_count == 1
        assert step.completed_at is not None

    def test_retry_cleanup_success_then_failed(self):
        step = TaskStep(tool="flaky_api")
        step.mark_running()
        step.mark_success(result="initial_ok")
        assert step.status == ActionStatus.SUCCESS
        assert step.result == "initial_ok"

        # Subsequent failure on retry
        step.mark_running()
        step.mark_failed(error="Unexpected disconnect")
        assert step.status == ActionStatus.FAILED
        assert step.error == "Unexpected disconnect"
        assert step.result is None  # Stale result must be cleared

    def test_full_repository_task_roundtrip(self):
        import tempfile, os
        from nova.agent.task_repository import SQLiteTaskRepository

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            repo = SQLiteTaskRepository(db_path)
            now = datetime.utcnow()

            task = Task(
                id="task-complete-roundtrip",
                session_id="sess-alpha",
                title="Full Lifecycle Task",
                description="Auditing complete roundtrip persistence",
                status=TaskStatus.RUNNING,
                priority=TaskPriority.URGENT,
                current_step_index=1,
                created_at=now,
                updated_at=now,
                started_at=now,
                completed_at=None,
                max_steps=20,
                wall_clock_timeout_seconds=900,
                metadata={"category": "audit", "retry_policy": "exponential"},
                error=None,
            )

            # Step 0: SUCCESS
            s0 = TaskStep(
                step_id="step-0",
                step_index=0,
                tool="prep",
                parameters={"flag": True},
                description="Preparation",
                status=ActionStatus.SUCCESS,
                result={"ready": True},
                error=None,
                execution_time_ms=12,
                started_at=now,
                completed_at=now,
                retry_count=0,
                max_retries=2,
            )
            # Step 1: RUNNING
            s1 = TaskStep(
                step_id="step-1",
                step_index=1,
                tool="fetch",
                parameters={"url": "https://example.com"},
                description="Fetch data",
                status=ActionStatus.RUNNING,
                started_at=now,
                completed_at=None,
                retry_count=1,
                max_retries=3,
            )
            # Step 2: PENDING
            s2 = TaskStep(
                step_id="step-2",
                step_index=2,
                tool="process",
                parameters={"mode": "batch"},
                description="Process data",
                status=ActionStatus.PENDING,
            )

            task.steps = [s0, s1, s2]

            # 1. Task -> TaskRecord
            record = task.to_record()
            # 2. TaskRecord -> Repository
            repo.create(record)

            # 3. Repository -> TaskRecord
            fetched_record = repo.get(task.id)
            assert fetched_record is not None

            # 4. TaskRecord -> Task
            restored_task = fetched_record.to_task()

            # Verify ALL meaningful fields survive
            assert restored_task.id == task.id
            assert restored_task.session_id == task.session_id
            assert restored_task.title == task.title
            assert restored_task.description == task.description
            assert restored_task.status == task.status
            assert restored_task.priority == task.priority
            assert restored_task.current_step_index == task.current_step_index
            assert restored_task.max_steps == task.max_steps
            assert restored_task.wall_clock_timeout_seconds == task.wall_clock_timeout_seconds
            assert restored_task.metadata == task.metadata
            assert restored_task.error == task.error
            assert restored_task.started_at is not None

            # Verify all 3 steps and their execution states
            assert len(restored_task.steps) == 3

            step0 = restored_task.steps[0]
            assert step0.step_id == "step-0"
            assert step0.step_index == 0
            assert step0.tool == "prep"
            assert step0.parameters == {"flag": True}
            assert step0.description == "Preparation"
            assert step0.status == ActionStatus.SUCCESS
            assert step0.result == {"ready": True}
            assert step0.error is None
            assert step0.execution_time_ms == 12
            assert step0.retry_count == 0
            assert step0.max_retries == 2

            step1 = restored_task.steps[1]
            assert step1.step_id == "step-1"
            assert step1.step_index == 1
            assert step1.tool == "fetch"
            assert step1.status == ActionStatus.RUNNING
            assert step1.retry_count == 1
            assert step1.max_retries == 3

            step2 = restored_task.steps[2]
            assert step2.step_id == "step-2"
            assert step2.step_index == 2
            assert step2.tool == "process"
            assert step2.status == ActionStatus.PENDING

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

    def test_all_five_step_statuses_preserved_in_repository(self):
        import tempfile, os
        from nova.agent.task_repository import SQLiteTaskRepository

        with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
            db_path = f.name

        try:
            repo = SQLiteTaskRepository(db_path)
            now = datetime.utcnow()

            task = Task(id="all-statuses-task", session_id="s1")
            task.steps = [
                TaskStep(step_index=0, tool="t0", status=ActionStatus.PENDING),
                TaskStep(step_index=1, tool="t1", status=ActionStatus.RUNNING, started_at=now),
                TaskStep(step_index=2, tool="t2", status=ActionStatus.SUCCESS, result={"ok": 1}, execution_time_ms=15, completed_at=now),
                TaskStep(step_index=3, tool="t3", status=ActionStatus.FAILED, error="bad parameter", execution_time_ms=20, completed_at=now),
                TaskStep(step_index=4, tool="t4", status=ActionStatus.SKIPPED, error="dependency failed", completed_at=now),
            ]

            rec = task.to_record()
            repo.create(rec)

            fetched = repo.get("all-statuses-task").to_task()
            assert len(fetched.steps) == 5
            assert fetched.steps[0].status == ActionStatus.PENDING
            assert fetched.steps[1].status == ActionStatus.RUNNING
            assert fetched.steps[2].status == ActionStatus.SUCCESS
            assert fetched.steps[2].result == {"ok": 1}
            assert fetched.steps[3].status == ActionStatus.FAILED
            assert fetched.steps[3].error == "bad parameter"
            assert fetched.steps[4].status == ActionStatus.SKIPPED
            assert fetched.steps[4].error == "dependency failed"

        finally:
            if os.path.exists(db_path):
                os.unlink(db_path)

