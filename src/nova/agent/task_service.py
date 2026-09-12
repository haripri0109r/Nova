"""TaskService – high‑level API for durable task management."""
from __future__ import annotations
import asyncio
from typing import Optional, List
from datetime import datetime

from .models import TaskRecord, TaskStatus, TaskPriority, TaskStep, ExecutionContext, ExecutionPlan, ActionStatus
from .task_repository import TaskRepository, get_task_repository
from .task_controller import TaskController, TaskPaused, TaskCancelled
from .exceptions import (
    TaskInterruptedStepError,
    StepNotInterruptedError,
    StepRetryLimitExceededError,
)
from ..events import get_event_bus
from ..events.events import (
    TaskCreatedEvent, TaskPausedEvent, TaskCancelledEvent,
    TaskResumedEvent, TaskCompletedEvent, TaskFailedEvent,
    StepStartedEvent, StepCompletedEvent, StepInterruptedEvent,
    StepRetriedEvent, StepSkippedEvent,
)


class TaskService:
    """
    High‑level service for creating, pausing, cancelling, resuming tasks.
    """

    def __init__(self, repository: Optional[TaskRepository] = None):
        self._repo = repository or get_task_repository()
        self._lock = asyncio.Lock()

    async def recover_orphaned_tasks(self, active_task_ids: Optional[set[str]] = None) -> List[str]:
        """
        Scan SQLite for orphaned tasks left in RUNNING status and transition them to PAUSED,
        marking any in-flight RUNNING step as INTERRUPTED.
        Atomically claims each task via CAS.
        Returns list of recovered task IDs.
        """
        async with self._lock:
            running_tasks = await self._call_repo(self._repo.list, TaskStatus.RUNNING)
            active_set = set(active_task_ids or [])
            recovered_ids = []

            for record in running_tasks:
                if record.id in active_set:
                    continue

                original_updated_at = record.updated_at.isoformat()
                interrupted_steps: List[TaskStep] = []
                for step in record.steps:
                    if step.status == ActionStatus.RUNNING:
                        step.mark_interrupted("Process terminated during execution")
                        interrupted_steps.append(step)

                record.status = TaskStatus.PAUSED
                record.updated_at = datetime.utcnow()
                record.metadata.setdefault("recovery_audit", []).append({
                    "action": "crash_recovery",
                    "recovered_at": record.updated_at.isoformat(),
                    "interrupted_steps": [s.step_index for s in interrupted_steps],
                })

                claimed = await self._call_repo(
                    self._repo.claim_and_recover_task,
                    record,
                    expected_updated_at=original_updated_at,
                )
                if claimed:
                    recovered_ids.append(record.id)
                    try:
                        bus = get_event_bus()
                        for step in interrupted_steps:
                            bus.publish(StepInterruptedEvent(
                                source="task_service",
                                payload={
                                    "task_id": record.id,
                                    "step_index": step.step_index,
                                    "tool": step.tool,
                                    "reason": "Process terminated during execution",
                                },
                            ))
                        bus.publish(TaskPausedEvent(
                            source="task_service",
                            payload={
                                "task_id": record.id,
                                "step_index": record.current_step,
                                "reason": "recovered_after_crash",
                            },
                        ))
                    except Exception as e:
                        import logging
                        logging.getLogger("nova.agent.task_service").error(
                            f"Failed to publish recovery events for task {record.id}: {e}"
                        )
            return recovered_ids

    async def _call_repo(self, func, *args, **kwargs):
        """Invoke repository operation without blocking the event loop or awaiting sync methods."""
        if asyncio.iscoroutinefunction(func):
            return await func(*args, **kwargs)
        return await asyncio.to_thread(func, *args, **kwargs)

    async def create_task(
        self,
        plan: "ExecutionPlan",
        context: ExecutionContext,
        session_id: str,
        title: str = "",
        description: str = "",
        priority: TaskPriority = TaskPriority.NORMAL,
    ) -> str:
        """
        Persist a new task and emit TaskCreatedEvent.
        Returns the task_id.
        """
        # Ensure context has task_id
        task_id = context.task_id or context.execution_id
        steps = [TaskStep.from_tool_action(action, step_index=i) for i, action in enumerate(plan.steps)]
        record = TaskRecord(
            id=task_id,
            plan=plan,
            context=context,
            status=TaskStatus.RUNNING,
            current_step=-1,
            title=title,
            description=description,
            priority=priority,
            steps=steps,
            max_steps=context.max_steps,
            wall_clock_timeout_seconds=context.wall_clock_timeout_seconds,
        )
        await self._call_repo(self._repo.create, record)

        # Emit event
        bus = get_event_bus()
        bus.publish(TaskCreatedEvent(
            source="task_service",
            payload={"task_id": task_id, "plan_summary": f"{len(plan.steps)} steps"},
        ))
        return task_id

    async def get_task(self, task_id: str) -> Optional[TaskRecord]:
        return await self._call_repo(self._repo.get, task_id)

    async def list_tasks(self, status: Optional[TaskStatus] = None) -> List[TaskRecord]:
        return await self._call_repo(self._repo.list, status)

    async def update_task(self, record: TaskRecord) -> None:
        """Persist in-flight task updates (e.g. current step, modified steps, error)."""
        record.updated_at = datetime.utcnow()
        await self._call_repo(self._repo.update, record)

    async def update_step_state(self, task_id: str, step: TaskStep, task: Optional[Any] = None) -> None:
        """
        Update durable step state and emit corresponding StepStartedEvent or StepCompletedEvent.
        Called by on_step_update from orchestrator.
        """
        record = await self._call_repo(self._repo.get, task_id)
        if not record:
            return

        from .models import ActionStatus

        # Sync steps into record
        if task is not None and hasattr(task, 'steps'):
            record.steps = task.steps
            record.current_step = task.current_step_index
        else:
            for i, s in enumerate(record.steps):
                if s.step_index == step.step_index or s.step_id == step.step_id:
                    record.steps[i] = step
                    break
            record.current_step = step.step_index

        record.updated_at = datetime.utcnow()
        await self._call_repo(self._repo.update, record)

        bus = get_event_bus()
        if step.status == ActionStatus.RUNNING:
            bus.publish(StepStartedEvent(
                source="task_service",
                payload={"task_id": task_id, "step_index": step.step_index, "tool": step.tool},
            ))
        elif step.status in (ActionStatus.SUCCESS, ActionStatus.FAILED, ActionStatus.SKIPPED):
            detail_msg = ""
            if isinstance(step.result, dict):
                detail_msg = step.result.get("detail", "")
            elif step.result is not None:
                detail_msg = str(step.result)
            bus.publish(StepCompletedEvent(
                source="task_service",
                payload={
                    "task_id": task_id,
                    "step_index": step.step_index,
                    "tool": step.tool,
                    "success": (step.status == ActionStatus.SUCCESS),
                    "detail": detail_msg,
                    "error": step.error,
                },
            ))

    async def pause_task(self, task_id: str, session_id: str) -> bool:
        """Pause a running task. Returns True if paused."""
        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                return False
            if record.context.session_id != session_id:
                raise PermissionError("Task belongs to different session")
            if record.status != TaskStatus.RUNNING:
                return False  # only running tasks can be paused
            record.status = TaskStatus.PAUSED
            record.updated_at = datetime.utcnow()
            await self._call_repo(self._repo.update, record)

            bus = get_event_bus()
            bus.publish(TaskPausedEvent(
                source="task_service",
                payload={"task_id": task_id, "step_index": record.current_step, "reason": "user requested"},
            ))
            return True

    async def cancel_task(self, task_id: str, session_id: str) -> bool:
        """Cancel a running/paused task."""
        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                return False
            if record.context.session_id != session_id:
                raise PermissionError("Task belongs to different session")
            if record.status == TaskStatus.CANCELLED:
                return True  # idempotent success, no duplicate event
            if record.status not in (TaskStatus.RUNNING, TaskStatus.PAUSED):
                return False  # cannot cancel completed or failed tasks
            record.status = TaskStatus.CANCELLED
            record.updated_at = datetime.utcnow()
            await self._call_repo(self._repo.update, record)

            bus = get_event_bus()
            bus.publish(TaskCancelledEvent(
                source="task_service",
                payload={"task_id": task_id, "step_index": record.current_step, "reason": "user requested"},
            ))
            return True

    async def resume_task(self, task_id: str, session_id: str) -> Optional[ExecutionContext]:
        """
        Resume a paused task. Transitions status PAUSED -> RUNNING, persists,
        and returns the restored ExecutionContext.
        NOTE: TaskService DOES NOT execute task steps.
        """
        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                return None
            if record.context.session_id != session_id:
                raise PermissionError("Task belongs to different session")
            if record.status != TaskStatus.PAUSED:
                return None  # only paused tasks can be resumed

            # Resume safety: check for unresolved INTERRUPTED steps
            for step in record.steps:
                if step.status == ActionStatus.INTERRUPTED:
                    raise TaskInterruptedStepError(
                        task_id=task_id,
                        step_index=step.step_index,
                        tool=step.tool,
                    )

            # Prepare context for resume: transition to RUNNING
            record.status = TaskStatus.RUNNING
            record.updated_at = datetime.utcnow()
            await self._call_repo(self._repo.update, record)

            bus = get_event_bus()
            bus.publish(TaskResumedEvent(
                source="task_service",
                payload={"task_id": task_id, "step_index": record.current_step + 1},
            ))
            return record.context


    # ------------------------------------------------------------------
    # PHASE 5.3C-B: Interrupted Step Remediation
    # ------------------------------------------------------------------

    async def retry_step(
        self,
        task_id: str,
        step_index: int,
        session_id: str,
        max_retries: int = 3,
    ) -> TaskStep:
        """
        Prepare an INTERRUPTED step for retry by transitioning it back to PENDING.

        Invariants enforced:
        - Target step MUST be ActionStatus.INTERRUPTED (raises StepNotInterruptedError).
        - step.retry_count MUST be < max_retries (raises StepRetryLimitExceededError).
        - Task MUST be PAUSED or FAILED (only those states have INTERRUPTED steps).
        - Task is transitioned PAUSED/FAILED → PAUSED to accept the next resume.
        - step.retry_count is incremented before persisting.
        - StepRetriedEvent is emitted after successful persist.
        - ZERO autonomous execution: TaskService only clears the block; execution
          requires an explicit subsequent RESUME command.

        Returns the updated TaskStep.
        """
        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                from .exceptions import AgentError
                raise AgentError(f"Task '{task_id}' not found", code="TASK_NOT_FOUND")

            if record.context.session_id != session_id:
                raise PermissionError("Task belongs to a different session")

            if record.status not in (TaskStatus.PAUSED, TaskStatus.FAILED):
                from .exceptions import AgentError
                raise AgentError(
                    f"RETRY_STEP requires task status PAUSED or FAILED, got {record.status.value}",
                    code="INVALID_STATE",
                )

            # Locate the target step
            target: Optional[TaskStep] = None
            for step in record.steps:
                if step.step_index == step_index:
                    target = step
                    break
            if target is None:
                from .exceptions import AgentError
                raise AgentError(
                    f"Step {step_index} does not exist in task '{task_id}'",
                    code="STEP_NOT_FOUND",
                )

            # Validate INTERRUPTED precondition
            if target.status != ActionStatus.INTERRUPTED:
                raise StepNotInterruptedError(
                    task_id=task_id,
                    step_index=step_index,
                    actual_status=target.status.value,
                )

            # Validate retry budget
            new_retry_count = target.retry_count + 1
            if new_retry_count > max_retries:
                raise StepRetryLimitExceededError(
                    task_id=task_id,
                    step_index=step_index,
                    retry_count=target.retry_count,
                    max_retries=max_retries,
                )

            # Apply state change: INTERRUPTED → PENDING, increment retry counter
            target.retry_count = new_retry_count
            target.to_pending()  # clears error/result/timestamps, sets PENDING

            # Ensure task is PAUSED (not FAILED) to allow a future RESUME
            if record.status == TaskStatus.FAILED:
                record.status = TaskStatus.PAUSED
            record.updated_at = datetime.utcnow()
            record.metadata.setdefault("remediation_audit", []).append({
                "action": "retry_step",
                "step_index": step_index,
                "tool": target.tool,
                "retry_count": new_retry_count,
                "at": record.updated_at.isoformat(),
            })

            await self._call_repo(self._repo.update, record)

            # Publish event AFTER successful persist
            try:
                bus = get_event_bus()
                bus.publish(StepRetriedEvent(
                    source="task_service",
                    payload={
                        "task_id": task_id,
                        "step_index": step_index,
                        "tool": target.tool,
                        "retry_count": new_retry_count,
                    },
                ))
            except Exception as exc:
                import logging as _logging
                _logging.getLogger("nova.agent.task_service").error(
                    "Failed to publish StepRetriedEvent for task %s step %s: %s",
                    task_id, step_index, exc,
                )

            return target

    async def skip_step(
        self,
        task_id: str,
        step_index: int,
        session_id: str,
        reason: str = "User requested skip",
    ) -> TaskStep:
        """
        Mark an INTERRUPTED step as SKIPPED, removing the resume block.

        Invariants enforced:
        - Target step MUST be ActionStatus.INTERRUPTED (raises StepNotInterruptedError).
        - Task MUST be PAUSED or FAILED.
        - Task is transitioned PAUSED/FAILED → PAUSED.
        - Downstream steps that depend_on the skipped step will be handled by
          PlanExecutor's dependency check (they will be auto-skipped at runtime).
        - StepSkippedEvent is emitted after successful persist.
        - ZERO autonomous execution.

        Returns the updated TaskStep.
        """
        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                from .exceptions import AgentError
                raise AgentError(f"Task '{task_id}' not found", code="TASK_NOT_FOUND")

            if record.context.session_id != session_id:
                raise PermissionError("Task belongs to a different session")

            if record.status not in (TaskStatus.PAUSED, TaskStatus.FAILED):
                from .exceptions import AgentError
                raise AgentError(
                    f"SKIP_STEP requires task status PAUSED or FAILED, got {record.status.value}",
                    code="INVALID_STATE",
                )

            # Locate the target step
            target: Optional[TaskStep] = None
            for step in record.steps:
                if step.step_index == step_index:
                    target = step
                    break
            if target is None:
                from .exceptions import AgentError
                raise AgentError(
                    f"Step {step_index} does not exist in task '{task_id}'",
                    code="STEP_NOT_FOUND",
                )

            # Validate INTERRUPTED precondition
            if target.status != ActionStatus.INTERRUPTED:
                raise StepNotInterruptedError(
                    task_id=task_id,
                    step_index=step_index,
                    actual_status=target.status.value,
                )

            # Apply state change: INTERRUPTED → SKIPPED
            target.mark_skipped(reason)

            # Ensure task is PAUSED to allow a future RESUME
            if record.status == TaskStatus.FAILED:
                record.status = TaskStatus.PAUSED
            record.updated_at = datetime.utcnow()
            record.metadata.setdefault("remediation_audit", []).append({
                "action": "skip_step",
                "step_index": step_index,
                "tool": target.tool,
                "reason": reason,
                "at": record.updated_at.isoformat(),
            })

            await self._call_repo(self._repo.update, record)

            # Publish event AFTER successful persist
            try:
                bus = get_event_bus()
                bus.publish(StepSkippedEvent(
                    source="task_service",
                    payload={
                        "task_id": task_id,
                        "step_index": step_index,
                        "tool": target.tool,
                        "reason": reason,
                    },
                ))
            except Exception as exc:
                import logging as _logging
                _logging.getLogger("nova.agent.task_service").error(
                    "Failed to publish StepSkippedEvent for task %s step %s: %s",
                    task_id, step_index, exc,
                )

            return target

    async def complete_task(self, task_id: str, summary: str = "") -> None:

        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                return
            if record.status != TaskStatus.RUNNING:
                return  # cannot complete non-running (e.g. cancelled/paused/failed) task
            record.status = TaskStatus.COMPLETED
            record.completed_at = datetime.utcnow()
            record.updated_at = datetime.utcnow()
            await self._call_repo(self._repo.update, record)

            bus = get_event_bus()
            bus.publish(TaskCompletedEvent(
                source="task_service",
                payload={"task_id": task_id, "summary": summary},
            ))

    async def fail_task(self, task_id: str, error: str) -> None:
        async with self._lock:
            record = await self._call_repo(self._repo.get, task_id)
            if not record:
                return
            if record.status.is_terminal():
                return
            record.status = TaskStatus.FAILED
            record.error = error
            record.completed_at = datetime.utcnow()
            record.updated_at = datetime.utcnow()
            await self._call_repo(self._repo.update, record)

            bus = get_event_bus()
            bus.publish(TaskFailedEvent(
                source="task_service",
                payload={"task_id": task_id, "step_index": record.current_step, "error": error},
            ))


# Global singleton
_task_service: Optional[TaskService] = None


def get_task_service() -> TaskService:
    global _task_service
    if _task_service is None:
        _task_service = TaskService()
    return _task_service