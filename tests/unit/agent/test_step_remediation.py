"""
Unit tests for Phase 5.3C-B: Interrupted Step Remediation.

Covers:
- TaskService.retry_step / skip_step core state machine
- TaskCommandRouter.RETRY_STEP / SKIP_STEP routing
- StepRiskPolicy risk classification
- ConfirmationManager token lifecycle (issue, claim, expire, mismatch)
- High-risk retry confirmation flow
- Retry limit enforcement
- FAILED → PAUSED recovery
- Zero autonomous replay guarantee
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from nova.agent.models import (
    ActionStatus,
    ExecutionContext,
    ExecutionPlan,
    TaskAction,
    TaskCommand,
    TaskRecord,
    TaskStatus,
    TaskStep,
)
from nova.agent.exceptions import (
    StepNotInterruptedError,
    StepRetryLimitExceededError,
    ConfirmationExpiredError,
    ConfirmationMismatchError,
)
from nova.agent.step_risk_policy import (
    ConfirmationManager,
    RiskLevel,
    classify_step_risk,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_step(
    step_index: int,
    tool: str = "read_file",
    status: ActionStatus = ActionStatus.INTERRUPTED,
    retry_count: int = 0,
) -> TaskStep:
    step = TaskStep(
        step_index=step_index,
        tool=tool,
        parameters={},
        description=f"Step {step_index}",
    )
    step.status = status
    step.retry_count = retry_count
    if status == ActionStatus.INTERRUPTED:
        # bypass guard for test setup
        step.status = ActionStatus.INTERRUPTED
        step.error = "Process terminated"
    return step


def _make_record(
    task_id: str = "t1",
    session_id: str = "sess-1",
    status: TaskStatus = TaskStatus.PAUSED,
    steps: Optional[List[TaskStep]] = None,
) -> TaskRecord:
    context = ExecutionContext(session_id=session_id, execution_id="exec-1")
    plan = ExecutionPlan(goal="test goal")
    record = TaskRecord(
        id=task_id,
        title="Test Task",
        status=status,
        context=context,
        plan=plan,
    )
    record.steps = steps or [_make_step(0, "read_file", ActionStatus.INTERRUPTED)]
    return record


# ---------------------------------------------------------------------------
# 1. StepRiskPolicy — risk classification
# ---------------------------------------------------------------------------


class TestStepRiskPolicy:
    def test_low_risk_tool(self):
        assert classify_step_risk("read_file") == RiskLevel.LOW

    def test_low_risk_unknown_tool(self):
        assert classify_step_risk("some_unknown_tool_xyz") == RiskLevel.LOW

    def test_high_risk_delete(self):
        assert classify_step_risk("delete_file") == RiskLevel.HIGH

    def test_high_risk_send_email(self):
        assert classify_step_risk("send_email") == RiskLevel.HIGH

    def test_high_risk_http_post(self):
        assert classify_step_risk("http_post") == RiskLevel.HIGH

    def test_high_risk_charge_payment(self):
        assert classify_step_risk("charge_payment") == RiskLevel.HIGH

    def test_high_risk_run_command(self):
        assert classify_step_risk("run_command") == RiskLevel.HIGH

    def test_case_insensitive(self):
        assert classify_step_risk("DELETE_FILE") == RiskLevel.HIGH
        assert classify_step_risk("Delete_File") == RiskLevel.HIGH

    def test_empty_tool(self):
        assert classify_step_risk("") == RiskLevel.LOW

    def test_none_tool(self):
        assert classify_step_risk(None) == RiskLevel.LOW


# ---------------------------------------------------------------------------
# 2. ConfirmationManager — token lifecycle
# ---------------------------------------------------------------------------


class TestConfirmationManager:
    def setup_method(self):
        self.cm = ConfirmationManager(ttl_seconds=60)

    def test_issue_returns_token(self):
        p = self.cm.issue("task-1", 0, "delete_file")
        assert len(p.token) == 16
        assert p.task_id == "task-1"
        assert p.step_index == 0

    def test_claim_valid_token(self):
        p = self.cm.issue("task-1", 0, "delete_file")
        result = self.cm.claim("task-1", 0, p.token)
        assert result is True

    def test_claim_single_use(self):
        p = self.cm.issue("task-1", 0, "delete_file")
        self.cm.claim("task-1", 0, p.token)
        # Second claim — token already deleted
        result = self.cm.claim("task-1", 0, p.token)
        assert result is False

    def test_claim_wrong_token_raises_mismatch(self):
        self.cm.issue("task-1", 0, "delete_file")
        with pytest.raises(ConfirmationMismatchError):
            self.cm.claim("task-1", 0, "badtoken")

    def test_claim_expired_raises_expired(self):
        cm = ConfirmationManager(ttl_seconds=0)
        p = cm.issue("task-1", 0, "delete_file")
        # Expire immediately (ttl=0 means already expired at issue time)
        import time; time.sleep(0.01)
        with pytest.raises(ConfirmationExpiredError):
            cm.claim("task-1", 0, p.token)

    def test_claim_no_pending_returns_false(self):
        result = self.cm.claim("no-such-task", 99, "anytoken")
        assert result is False

    def test_issue_supersedes_old_token(self):
        p1 = self.cm.issue("task-1", 0, "delete_file")
        p2 = self.cm.issue("task-1", 0, "delete_file")
        assert p1.token != p2.token
        # Old token deleted; claim with old fails with False (no pending) or mismatch
        # Since p2 supersedes p1 in _pending, claiming p1 raises mismatch
        with pytest.raises(ConfirmationMismatchError):
            self.cm.claim("task-1", 0, p1.token)

    def test_has_pending_true(self):
        self.cm.issue("task-1", 0, "delete_file")
        assert self.cm.has_pending("task-1", 0) is True

    def test_has_pending_false_after_claim(self):
        p = self.cm.issue("task-1", 0, "delete_file")
        self.cm.claim("task-1", 0, p.token)
        assert self.cm.has_pending("task-1", 0) is False

    def test_clear(self):
        self.cm.issue("task-1", 0, "delete_file")
        self.cm.clear("task-1", 0)
        assert self.cm.has_pending("task-1", 0) is False

    def test_different_step_independent(self):
        p0 = self.cm.issue("task-1", 0, "delete_file")
        p1 = self.cm.issue("task-1", 1, "send_email")
        assert self.cm.claim("task-1", 0, p0.token) is True
        assert self.cm.claim("task-1", 1, p1.token) is True


# ---------------------------------------------------------------------------
# 3. TaskService.retry_step — core state machine
# ---------------------------------------------------------------------------


class _FakeRepo:
    """In-memory TaskRepository stub."""
    def __init__(self, record: Optional[TaskRecord] = None):
        self.record = record

    async def get(self, task_id: str) -> Optional[TaskRecord]:
        return self.record if (self.record and self.record.id == task_id) else None

    async def update(self, record: TaskRecord) -> None:
        self.record = record

    async def create(self, record: TaskRecord) -> TaskRecord:
        self.record = record
        return record


def _make_service(record: Optional[TaskRecord] = None):
    from nova.agent.task_service import TaskService
    svc = TaskService.__new__(TaskService)
    svc._repo = _FakeRepo(record)
    svc._lock = asyncio.Lock()
    # Patch _call_repo to just call the method directly
    async def _call_repo(fn, *args, **kwargs):
        return await fn(*args, **kwargs)
    svc._call_repo = _call_repo
    return svc


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestTaskServiceRetryStep:
    @pytest.fixture(autouse=True)
    def patch_bus(self):
        """Suppress event bus calls."""
        with patch("nova.agent.task_service.get_event_bus") as mock_bus:
            bus = MagicMock()
            bus.publish = MagicMock()
            mock_bus.return_value = bus
            self.bus = bus
            yield

    def test_retry_step_interrupts_to_pending(self):
        record = _make_record(
            task_id="t1",
            status=TaskStatus.PAUSED,
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED, retry_count=0)],
        )
        svc = _make_service(record)

        async def run():
            step = await svc.retry_step("t1", 0, "sess-1", max_retries=3)
            return step

        step = asyncio.get_event_loop().run_until_complete(run())
        assert step.status == ActionStatus.PENDING
        assert step.retry_count == 1

    def test_retry_step_increments_counter(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED, retry_count=1)],
        )
        svc = _make_service(record)

        async def run():
            return await svc.retry_step("t1", 0, "sess-1", max_retries=3)

        step = asyncio.get_event_loop().run_until_complete(run())
        assert step.retry_count == 2

    def test_retry_step_limit_exceeded(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED, retry_count=3)],
        )
        svc = _make_service(record)

        async def run():
            await svc.retry_step("t1", 0, "sess-1", max_retries=3)

        with pytest.raises(StepRetryLimitExceededError):
            asyncio.get_event_loop().run_until_complete(run())

    def test_retry_step_not_interrupted(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.PENDING)],
        )
        svc = _make_service(record)

        async def run():
            await svc.retry_step("t1", 0, "sess-1", max_retries=3)

        with pytest.raises(StepNotInterruptedError):
            asyncio.get_event_loop().run_until_complete(run())

    def test_retry_step_failed_task_transitions_to_paused(self):
        record = _make_record(
            status=TaskStatus.FAILED,
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED)],
        )
        svc = _make_service(record)

        async def run():
            await svc.retry_step("t1", 0, "sess-1", max_retries=3)
            return svc._repo.record

        saved = asyncio.get_event_loop().run_until_complete(run())
        assert saved.status == TaskStatus.PAUSED

    def test_retry_step_publishes_event(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED)],
        )
        svc = _make_service(record)

        async def run():
            await svc.retry_step("t1", 0, "sess-1")

        asyncio.get_event_loop().run_until_complete(run())
        self.bus.publish.assert_called_once()
        evt = self.bus.publish.call_args[0][0]
        from nova.events.events import StepRetriedEvent
        assert isinstance(evt, StepRetriedEvent)

    def test_retry_step_wrong_session_rejected(self):
        record = _make_record(session_id="sess-A")
        svc = _make_service(record)

        async def run():
            await svc.retry_step("t1", 0, "sess-B")

        with pytest.raises(PermissionError):
            asyncio.get_event_loop().run_until_complete(run())

    def test_retry_step_task_not_found(self):
        svc = _make_service(None)

        async def run():
            await svc.retry_step("no-task", 0, "sess-1")

        from nova.agent.exceptions import AgentError
        with pytest.raises(AgentError):
            asyncio.get_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# 4. TaskService.skip_step — core state machine
# ---------------------------------------------------------------------------


class TestTaskServiceSkipStep:
    @pytest.fixture(autouse=True)
    def patch_bus(self):
        with patch("nova.agent.task_service.get_event_bus") as mock_bus:
            bus = MagicMock()
            bus.publish = MagicMock()
            mock_bus.return_value = bus
            self.bus = bus
            yield

    def test_skip_step_sets_skipped(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.INTERRUPTED)],
        )
        svc = _make_service(record)

        async def run():
            return await svc.skip_step("t1", 0, "sess-1")

        step = asyncio.get_event_loop().run_until_complete(run())
        assert step.status == ActionStatus.SKIPPED

    def test_skip_step_not_interrupted(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.SUCCESS)],
        )
        svc = _make_service(record)

        async def run():
            await svc.skip_step("t1", 0, "sess-1")

        with pytest.raises(StepNotInterruptedError):
            asyncio.get_event_loop().run_until_complete(run())

    def test_skip_step_failed_task_transitions_to_paused(self):
        record = _make_record(
            status=TaskStatus.FAILED,
            steps=[_make_step(0, "send_email", ActionStatus.INTERRUPTED)],
        )
        svc = _make_service(record)

        async def run():
            await svc.skip_step("t1", 0, "sess-1")
            return svc._repo.record

        saved = asyncio.get_event_loop().run_until_complete(run())
        assert saved.status == TaskStatus.PAUSED

    def test_skip_step_publishes_event(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.INTERRUPTED)],
        )
        svc = _make_service(record)

        async def run():
            await svc.skip_step("t1", 0, "sess-1")

        asyncio.get_event_loop().run_until_complete(run())
        self.bus.publish.assert_called_once()
        evt = self.bus.publish.call_args[0][0]
        from nova.events.events import StepSkippedEvent
        assert isinstance(evt, StepSkippedEvent)

    def test_skip_step_wrong_session_rejected(self):
        record = _make_record(session_id="sess-A")
        svc = _make_service(record)

        async def run():
            await svc.skip_step("t1", 0, "sess-B")

        with pytest.raises(PermissionError):
            asyncio.get_event_loop().run_until_complete(run())


# ---------------------------------------------------------------------------
# 5. TaskStatus state machine — FAILED → PAUSED transition
# ---------------------------------------------------------------------------


class TestTaskStatusTransitions:
    def test_failed_can_transition_to_paused(self):
        assert TaskStatus.FAILED.can_transition_to(TaskStatus.PAUSED) is True

    def test_failed_cannot_transition_to_running(self):
        assert TaskStatus.FAILED.can_transition_to(TaskStatus.RUNNING) is False

    def test_completed_is_terminal(self):
        assert TaskStatus.COMPLETED.is_terminal() is True

    def test_cancelled_is_terminal(self):
        assert TaskStatus.CANCELLED.is_terminal() is True

    def test_failed_is_not_terminal(self):
        # FAILED can become PAUSED, so it is not fully terminal
        assert TaskStatus.FAILED.is_terminal() is False

    def test_paused_is_not_terminal(self):
        assert TaskStatus.PAUSED.is_terminal() is False


# ---------------------------------------------------------------------------
# 6. TaskCommandRouter — RETRY_STEP routing
# ---------------------------------------------------------------------------


def _make_router_with_task(record: TaskRecord):
    """Build a TaskCommandRouter with an in-memory service stub."""
    from nova.agent.task_command_router import TaskCommandRouter
    from nova.agent.task_service import TaskService
    from nova.agent.task_resolver import TaskResolver

    svc = _make_service(record)

    class _StubResolver:
        async def resolve(self, command):
            from nova.agent.task_resolver import TaskResolutionResult, ResolutionStatus
            return TaskResolutionResult(
                status=ResolutionStatus.RESOLVED,
                task=record,
            )

    router = TaskCommandRouter(
        resolver=_StubResolver(),
        orchestrator=None,
        task_service=svc,
    )
    return router, svc


class TestTaskCommandRouterRetryStep:
    @pytest.fixture(autouse=True)
    def patch_bus(self):
        with patch("nova.agent.task_service.get_event_bus") as mock_bus:
            bus = MagicMock()
            bus.publish = MagicMock()
            mock_bus.return_value = bus
            yield

    def test_retry_low_risk_success(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED)],
        )
        router, svc = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is True
        assert result.status == "PAUSED"

    def test_retry_high_risk_requires_confirmation(self):
        record = _make_record(
            steps=[_make_step(0, "delete_file", ActionStatus.INTERRUPTED)],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
            confirmed=False,
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is False
        assert result.error == "high_risk_confirmation_required"
        assert "token" in result.message.lower()

    def test_retry_high_risk_with_valid_token(self):
        record = _make_record(
            steps=[_make_step(0, "delete_file", ActionStatus.INTERRUPTED)],
        )
        router, svc = _make_router_with_task(record)

        # First call: get token
        cmd_no_confirm = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def first_call():
            return await router.route(cmd_no_confirm)

        r1 = asyncio.get_event_loop().run_until_complete(first_call())
        assert r1.error == "high_risk_confirmation_required"

        # Extract token from message
        import re
        token_match = re.search(r'token:\s*(\w+)', r1.message)
        assert token_match, f"No token in message: {r1.message}"
        token = token_match.group(1)

        # Re-sync record in svc (step still INTERRUPTED since first call didn't change state)
        router2, svc2 = _make_router_with_task(record)
        # Put the token into the shared confirmation manager
        from nova.agent.step_risk_policy import get_confirmation_manager
        get_confirmation_manager()._pending[("t1", 0)] = (
            get_confirmation_manager()._pending.get(("t1", 0))
        )

        # Second call: with token
        cmd_confirmed = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
            confirmed=True,
            confirmation_token=token,
        )

        async def second_call():
            return await router.route(cmd_confirmed)

        r2 = asyncio.get_event_loop().run_until_complete(second_call())
        assert r2.success is True
        assert r2.status == "PAUSED"

    def test_retry_no_interrupted_step_returns_error(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.SUCCESS)],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is False
        # Either no_interrupted_step (auto-detect) or step_not_interrupted
        assert result.error in ("no_interrupted_step", "step_not_interrupted")

    def test_retry_limit_exceeded(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED, retry_count=3)],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is False
        assert result.error == "retry_limit_exceeded"


# ---------------------------------------------------------------------------
# 7. TaskCommandRouter — SKIP_STEP routing
# ---------------------------------------------------------------------------


class TestTaskCommandRouterSkipStep:
    @pytest.fixture(autouse=True)
    def patch_bus(self):
        with patch("nova.agent.task_service.get_event_bus") as mock_bus:
            bus = MagicMock()
            bus.publish = MagicMock()
            mock_bus.return_value = bus
            yield

    def test_skip_step_success(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.INTERRUPTED)],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.SKIP_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is True
        assert result.status == "PAUSED"
        assert "skip" in result.message.lower()

    def test_skip_step_not_interrupted(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.SUCCESS)],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.SKIP_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is False
        assert result.error == "step_not_interrupted"

    def test_skip_step_auto_detects_first_interrupted(self):
        record = _make_record(
            steps=[
                _make_step(0, "read_file", ActionStatus.SUCCESS),
                _make_step(1, "send_email", ActionStatus.INTERRUPTED),
            ],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.SKIP_STEP,
            task_id="t1",
            session_id="sess-1",
            # step_index omitted — should auto-detect step 1
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is True

    def test_skip_no_interrupted_step_returns_error(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.PENDING)],
        )
        router, _ = _make_router_with_task(record)
        cmd = TaskCommand(
            action=TaskAction.SKIP_STEP,
            task_id="t1",
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is False
        assert result.error == "no_interrupted_step"


# ---------------------------------------------------------------------------
# 8. Zero autonomous replay guarantee
# ---------------------------------------------------------------------------


class TestZeroAutonomousReplay:
    """
    Verify that RETRY_STEP and SKIP_STEP NEVER auto-execute the step.
    They only change persistent state; a separate RESUME command is required.
    """

    @pytest.fixture(autouse=True)
    def patch_bus(self):
        with patch("nova.agent.task_service.get_event_bus") as mock_bus:
            bus = MagicMock()
            bus.publish = MagicMock()
            mock_bus.return_value = bus
            yield

    def test_retry_step_does_not_call_orchestrator(self):
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED)],
        )
        router, svc = _make_router_with_task(record)
        mock_orchestrator = MagicMock()
        router._orchestrator = mock_orchestrator

        cmd = TaskCommand(
            action=TaskAction.RETRY_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is True
        # Orchestrator must NOT have been called — no execution happens
        mock_orchestrator.resume_task.assert_not_called()
        mock_orchestrator.run_task.assert_not_called()

    def test_skip_step_does_not_call_orchestrator(self):
        record = _make_record(
            steps=[_make_step(0, "send_email", ActionStatus.INTERRUPTED)],
        )
        router, svc = _make_router_with_task(record)
        mock_orchestrator = MagicMock()
        router._orchestrator = mock_orchestrator

        cmd = TaskCommand(
            action=TaskAction.SKIP_STEP,
            task_id="t1",
            step_index=0,
            session_id="sess-1",
        )

        async def run():
            return await router.route(cmd)

        result = asyncio.get_event_loop().run_until_complete(run())
        assert result.success is True
        mock_orchestrator.resume_task.assert_not_called()
        mock_orchestrator.run_task.assert_not_called()

    def test_retry_step_only_pending_state_no_execution(self):
        """After retry_step, the step must be PENDING (awaiting RESUME), not running/success."""
        record = _make_record(
            steps=[_make_step(0, "read_file", ActionStatus.INTERRUPTED)],
        )
        svc = _make_service(record)

        async def run():
            await svc.retry_step("t1", 0, "sess-1")
            return svc._repo.record.steps[0].status

        status = asyncio.get_event_loop().run_until_complete(run())
        assert status == ActionStatus.PENDING  # not RUNNING, SUCCESS, etc.
