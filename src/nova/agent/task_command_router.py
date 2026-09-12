"""
TaskCommandRouter – high-level dispatcher for user task commands.

Dispatches validated TaskCommands (PAUSE, RESUME, CANCEL, STATUS, LIST) to the appropriate
subsystems without violating boundaries:
- Delegates resolution strictly to TaskResolver.
- Delegates live control to AgentOrchestrator.
- Queries task state through TaskService.
- ZERO direct access to SQLite, TaskRepository, TaskController internals, or asyncio.Event.
- Zero skill execution and zero lifecycle event publishing.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .models import (
    ActionStatus,
    TaskRecord,
    TaskStatus,
    TaskAction,
    TaskCommand,
)
from .task_resolver import (
    ResolutionStatus,
    TaskResolutionResult,
    TaskResolver,
)
from .task_service import TaskService, get_task_service

logger = logging.getLogger(__name__)


class TaskStatusDTO(BaseModel):
    """Clean data transfer object representing task status for user interfaces."""
    task_id: str
    title: str = ""
    status: str
    priority: str = "normal"
    pause_pending: bool = False
    current_step_index: int = -1
    total_steps: int = 0
    completed_steps: int = 0
    failed_steps: int = 0
    current_step_tool: str = ""
    current_step_description: str = ""
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None


class TaskCommandResult(BaseModel):
    """Outcome of routing a TaskCommand."""
    success: bool
    action: TaskAction
    message: str
    task_id: Optional[str] = None
    status: Optional[str] = None
    dto: Optional[TaskStatusDTO] = None
    list_dtos: Optional[List[TaskStatusDTO]] = None
    error: Optional[str] = None


class TaskCommandRouter:
    """
    Command-dispatch-only router for task lifecycle and query operations.

    Invariants:
    - Never accesses SQLite or TaskRepository.
    - Never manipulates TaskController or asyncio.Event directly.
    - Never publishes lifecycle events (TaskService is sole publisher).
    - Never executes skills or creates execution loops.
    """

    def __init__(
        self,
        resolver: Optional[TaskResolver] = None,
        orchestrator=None,
        task_service: Optional[TaskService] = None,
        task_resolver: Optional[TaskResolver] = None,
    ):
        self._resolver = resolver or task_resolver
        self._orchestrator = orchestrator
        self._task_service = task_service

    def _get_resolver(self) -> TaskResolver:
        if self._resolver is not None:
            return self._resolver
        return TaskResolver(self._get_task_service())

    def _get_orchestrator(self):
        if self._orchestrator is not None:
            return self._orchestrator
        from .orchestrator import get_agent_orchestrator
        return get_agent_orchestrator()

    def _get_task_service(self) -> TaskService:
        if self._task_service is not None:
            return self._task_service
        return get_task_service()

    def _build_dto(self, record: TaskRecord, pause_pending: bool = False) -> TaskStatusDTO:
        """Construct a TaskStatusDTO truthfully reflecting state and pending signals."""
        total = len(record.steps)
        completed = len([s for s in record.steps if s.status == ActionStatus.SUCCESS])
        failed = len([s for s in record.steps if s.status == ActionStatus.FAILED])

        tool = ""
        desc = ""
        if 0 <= record.current_step < total:
            tool = record.steps[record.current_step].tool
            desc = record.steps[record.current_step].description

        if record.status == TaskStatus.RUNNING and pause_pending:
            status_str = "RUNNING (pause requested)"
        else:
            status_str = record.status.value.upper()

        priority_str = (
            record.priority.value
            if hasattr(record.priority, "value")
            else str(record.priority)
        )

        return TaskStatusDTO(
            task_id=record.id,
            title=record.title or "",
            status=status_str,
            priority=priority_str,
            pause_pending=pause_pending,
            current_step_index=record.current_step,
            total_steps=total,
            completed_steps=completed,
            failed_steps=failed,
            current_step_tool=tool,
            current_step_description=desc,
            started_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
            error=record.error,
        )

    async def route(self, command: TaskCommand) -> TaskCommandResult:
        """
        Route a TaskCommand to resolver and corresponding subsystem.
        """
        resolver = self._get_resolver()
        resolution = await resolver.resolve(command)

        if resolution.status == ResolutionStatus.UNAUTHORIZED:
            return TaskCommandResult(
                success=False,
                action=command.action,
                task_id=command.task_id,
                message=resolution.error_message or f"Task '{command.task_id}' not found or access denied.",
                error="unauthorized",
            )

        if resolution.status == ResolutionStatus.AMBIGUOUS:
            return TaskCommandResult(
                success=False,
                action=command.action,
                task_id=command.task_id,
                message=resolution.error_message or "Multiple tasks match the request. Please specify exact task ID.",
                error="ambiguous",
            )

        if resolution.status == ResolutionStatus.NOT_FOUND:
            return TaskCommandResult(
                success=False,
                action=command.action,
                task_id=command.task_id,
                message=resolution.error_message or "Task not found.",
                error="not_found",
            )

        task = resolution.task
        orchestrator = self._get_orchestrator()

        # ------------------------------------------------------------------
        # PAUSE
        # ------------------------------------------------------------------
        if command.action == TaskAction.PAUSE:
            if not task:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    message="No target task to pause.",
                    error="not_found",
                )
            success = await orchestrator.pause_task(task.id, command.session_id)
            if success:
                return TaskCommandResult(
                    success=True,
                    action=command.action,
                    task_id=task.id,
                    status="RUNNING (pause requested)",
                    message=f"Task '{task.id}' pause requested (completing active step...)",
                )
            else:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    message=f"Task '{task.id}' could not be paused (current status: {task.status.value}).",
                    error="invalid_state",
                )

        # ------------------------------------------------------------------
        # RESUME
        # ------------------------------------------------------------------
        if command.action == TaskAction.RESUME:
            if not task:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    message="No target task to resume.",
                    error="not_found",
                )
            from .exceptions import TaskInterruptedStepError
            try:
                success = await orchestrator.request_resume(task.id, command.session_id)
            except TaskInterruptedStepError as e:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    status=task.status.value.upper(),
                    error="interrupted_step",
                    message=(
                        f"Cannot resume task '{task.id}': Step {e.step_index + 1} ({e.tool}) "
                        f"was interrupted during execution (outcome unknown). "
                        f"Please resolve before resuming."
                    ),
                )
            if success:
                return TaskCommandResult(
                    success=True,
                    action=command.action,
                    task_id=task.id,
                    status="RUNNING",
                    message=f"Task '{task.id}' resumed",
                )
            else:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    message=f"Task '{task.id}' could not be resumed (current status: {task.status.value}).",
                    error="invalid_state",
                )

        # ------------------------------------------------------------------
        # CANCEL
        # ------------------------------------------------------------------
        if command.action == TaskAction.CANCEL:
            if not task:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    message="No target task to cancel.",
                    error="not_found",
                )
            if task.status == TaskStatus.CANCELLED:
                return TaskCommandResult(
                    success=True,
                    action=command.action,
                    task_id=task.id,
                    status="CANCELLED",
                    message=f"Task '{task.id}' is already cancelled",
                )
            success = await orchestrator.cancel_task(task.id, command.session_id)
            if success:
                return TaskCommandResult(
                    success=True,
                    action=command.action,
                    task_id=task.id,
                    status="CANCELLED",
                    message=f"Task '{task.id}' cancelled",
                )
            else:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    message=f"Task '{task.id}' could not be cancelled (current status: {task.status.value}).",
                    error="invalid_state",
                )

        # ------------------------------------------------------------------
        # STATUS
        # ------------------------------------------------------------------
        if command.action == TaskAction.STATUS:
            if not task:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    message="No active task found.",
                    error="not_found",
                )
            pause_pending = orchestrator.is_pause_requested(task.id)
            dto = self._build_dto(task, pause_pending=pause_pending)
            msg = f"Task '{task.id}' [{dto.status}]: {dto.completed_steps}/{dto.total_steps} steps completed"
            if dto.current_step_tool:
                msg += f" (Current step: {dto.current_step_tool})"
            if dto.error:
                msg += f" Error: {dto.error}"
            return TaskCommandResult(
                success=True,
                action=command.action,
                task_id=task.id,
                status=dto.status,
                dto=dto,
                message=msg,
            )

        # ------------------------------------------------------------------
        # LIST
        # ------------------------------------------------------------------
        if command.action == TaskAction.LIST:
            tasks = resolution.matching_tasks
            dtos = [
                self._build_dto(t, pause_pending=orchestrator.is_pause_requested(t.id))
                for t in tasks
            ]
            if not dtos:
                msg = "No tasks found."
            else:
                lines = [f"Found {len(dtos)} task(s):"]
                for d in dtos:
                    title_part = f" - {d.title}" if d.title else ""
                    lines.append(f"• {d.task_id} [{d.status}]{title_part} ({d.completed_steps}/{d.total_steps} steps)")
                msg = "\n".join(lines)
            return TaskCommandResult(
                success=True,
                action=command.action,
                list_dtos=dtos,
                message=msg,
            )

        # ------------------------------------------------------------------
        # RETRY_STEP
        # ------------------------------------------------------------------
        if command.action == TaskAction.RETRY_STEP:
            if not task:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    message="No target task for RETRY_STEP.",
                    error="not_found",
                )

            step_index = command.step_index
            if step_index is None:
                # Default: find the first INTERRUPTED step
                for s in task.steps:
                    from .models import ActionStatus
                    if s.status == ActionStatus.INTERRUPTED:
                        step_index = s.step_index
                        break
                if step_index is None:
                    return TaskCommandResult(
                        success=False,
                        action=command.action,
                        task_id=task.id,
                        message="No INTERRUPTED step found to retry.",
                        error="no_interrupted_step",
                    )

            # Resolve target step for risk classification
            target_step = None
            for s in task.steps:
                if s.step_index == step_index:
                    target_step = s
                    break

            if target_step is None:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    message=f"Step {step_index} does not exist.",
                    error="step_not_found",
                )

            # Risk policy check
            from .step_risk_policy import classify_step_risk, RiskLevel, get_confirmation_manager
            risk = classify_step_risk(target_step.tool, target_step.parameters)
            if risk == RiskLevel.HIGH:
                cm = get_confirmation_manager()
                if not command.confirmed or not command.confirmation_token:
                    # Issue a new confirmation token
                    pending = cm.issue(task.id, step_index, target_step.tool)
                    return TaskCommandResult(
                        success=False,
                        action=command.action,
                        task_id=task.id,
                        status=task.status.value.upper(),
                        error="high_risk_confirmation_required",
                        message=(
                            f"Step {step_index} ({target_step.tool}) is HIGH RISK. "
                            f"Retrying may cause irreversible side effects (e.g. duplicate file delete, email, payment). "
                            f"To confirm, resend RETRY_STEP with token: {pending.token} "
                            f"(expires: {pending.expires_at.strftime('%H:%M:%S UTC')})."
                        ),
                    )
                else:
                    # Validate the token
                    from .exceptions import ConfirmationExpiredError, ConfirmationMismatchError
                    try:
                        valid = cm.claim(task.id, step_index, command.confirmation_token)
                        if not valid:
                            return TaskCommandResult(
                                success=False,
                                action=command.action,
                                task_id=task.id,
                                error="confirmation_mismatch",
                                message=f"Confirmation token does not match pending token for step {step_index}.",
                            )
                    except ConfirmationExpiredError as e:
                        return TaskCommandResult(
                            success=False,
                            action=command.action,
                            task_id=task.id,
                            error="confirmation_expired",
                            message=str(e),
                        )
                    except ConfirmationMismatchError as e:
                        return TaskCommandResult(
                            success=False,
                            action=command.action,
                            task_id=task.id,
                            error="confirmation_mismatch",
                            message=str(e),
                        )

            # Delegate to TaskService (durable state change + event emission)
            task_service = self._get_task_service()
            from .exceptions import StepNotInterruptedError, StepRetryLimitExceededError
            try:
                await task_service.retry_step(
                    task_id=task.id,
                    step_index=step_index,
                    session_id=command.session_id,
                )
            except StepNotInterruptedError as e:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    error="step_not_interrupted",
                    message=str(e),
                )
            except StepRetryLimitExceededError as e:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    error="retry_limit_exceeded",
                    message=str(e),
                )

            return TaskCommandResult(
                success=True,
                action=command.action,
                task_id=task.id,
                status="PAUSED",
                message=(
                    f"Step {step_index} ({target_step.tool}) marked for retry "
                    f"(attempt {target_step.retry_count + 1}). "
                    f"Issue RESUME to execute."
                ),
            )

        # ------------------------------------------------------------------
        # SKIP_STEP
        # ------------------------------------------------------------------
        if command.action == TaskAction.SKIP_STEP:
            if not task:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    message="No target task for SKIP_STEP.",
                    error="not_found",
                )

            step_index = command.step_index
            if step_index is None:
                # Default: find the first INTERRUPTED step
                for s in task.steps:
                    from .models import ActionStatus
                    if s.status == ActionStatus.INTERRUPTED:
                        step_index = s.step_index
                        break
                if step_index is None:
                    return TaskCommandResult(
                        success=False,
                        action=command.action,
                        task_id=task.id,
                        message="No INTERRUPTED step found to skip.",
                        error="no_interrupted_step",
                    )

            # Delegate to TaskService
            task_service = self._get_task_service()
            from .exceptions import StepNotInterruptedError
            try:
                skipped = await task_service.skip_step(
                    task_id=task.id,
                    step_index=step_index,
                    session_id=command.session_id,
                )
            except StepNotInterruptedError as e:
                return TaskCommandResult(
                    success=False,
                    action=command.action,
                    task_id=task.id,
                    error="step_not_interrupted",
                    message=str(e),
                )

            return TaskCommandResult(
                success=True,
                action=command.action,
                task_id=task.id,
                status="PAUSED",
                message=(
                    f"Step {step_index} ({skipped.tool}) skipped. "
                    f"Dependent steps will also be skipped at runtime. "
                    f"Issue RESUME to continue."
                ),
            )

        # ------------------------------------------------------------------
        # UNSUPPORTED (future phases)
        # ------------------------------------------------------------------
        return TaskCommandResult(
            success=False,
            action=command.action,
            message=f"Action '{command.action.value}' is not yet supported.",
            error="unsupported",
        )



_task_command_router: Optional[TaskCommandRouter] = None


def get_task_command_router() -> TaskCommandRouter:
    """Get or instantiate singleton TaskCommandRouter."""
    global _task_command_router
    if _task_command_router is None:
        _task_command_router = TaskCommandRouter()
    return _task_command_router
