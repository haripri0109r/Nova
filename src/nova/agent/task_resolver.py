"""
TaskResolver – stateless, deterministic, query-only task resolution.

Resolves a structured TaskCommand (session_id, task_id?, action) to a deterministic
TaskResolutionResult without mutating any task state.

INVARIANTS:
- Depends ONLY on TaskService query APIs.
- ZERO direct access to TaskRepository, SQLite, or database connections.
- Stateless, deterministic, query-only.
- Zero task mutations, zero events published, zero skill execution.
- Strict session isolation: foreign session tasks return UNAUTHORIZED with privacy-safe message.
- Minimum 4 characters required for prefix matching.
- STATUS with no task ID queries RUNNING + PAUSED tasks: exactly 1 -> RESOLVED, >1 -> AMBIGUOUS, 0 -> NOT_FOUND.
- No silent fallback to arbitrary recency or completed tasks.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional
from pydantic import BaseModel, Field

from .models import TaskRecord, TaskStatus, TaskAction, TaskCommand
from .task_service import TaskService, get_task_service


class ResolutionStatus(str, Enum):
    """Status outcomes for task identification/resolution."""
    RESOLVED = "resolved"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"
    UNAUTHORIZED = "unauthorized"


class TaskResolutionResult(BaseModel):
    """Outcome of resolving a TaskCommand against task state."""
    status: ResolutionStatus
    task: Optional[TaskRecord] = None
    matching_tasks: List[TaskRecord] = Field(default_factory=list)
    error_message: Optional[str] = None


class TaskResolver:
    """
    Stateless, deterministic, query-only task resolver.
    
    Invariants:
    - Depends ONLY on TaskService.
    - Zero access to SQLite or TaskRepository.
    - Never mutates tasks or task steps.
    - Never executes skills or invokes orchestrator.
    - Enforces session isolation: tasks belonging to other sessions return UNAUTHORIZED.
    - Prefix matching requires at least 4 characters to prevent collisions.
    - Implicit resolution uses action and state semantics deterministically.
    """

    def __init__(self, task_service: Optional[TaskService] = None):
        self._service = task_service

    def _get_service(self) -> TaskService:
        if self._service is not None:
            return self._service
        return get_task_service()

    async def resolve(self, command: TaskCommand) -> TaskResolutionResult:
        """
        Asynchronously resolve a TaskCommand using TaskService query methods.
        """
        service = self._get_service()
        target_id = command.task_id.strip() if command.task_id else None

        # ------------------------------------------------------------------
        # 1. Explicit ID / Prefix resolution
        # ------------------------------------------------------------------
        if target_id:
            # 1a. Try exact match first
            exact_match = await service.get_task(target_id)
            if exact_match is not None:
                record_session = (
                    exact_match.context.session_id
                    if exact_match.context and exact_match.context.session_id
                    else "default"
                )
                if record_session == command.session_id:
                    return TaskResolutionResult(
                        status=ResolutionStatus.RESOLVED,
                        task=exact_match,
                        matching_tasks=[exact_match],
                    )
                else:
                    # Foreign session: privacy-safe response
                    return TaskResolutionResult(
                        status=ResolutionStatus.UNAUTHORIZED,
                        error_message=f"Task '{target_id}' not found or access denied.",
                    )

            # 1b. Prefix matching (minimum 4 characters)
            if len(target_id) < 4:
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"Task '{target_id}' not found (prefix search requires at least 4 characters)",
                )

            all_records = await service.list_tasks()
            session_matches = [
                r for r in all_records
                if (r.context.session_id if r.context and r.context.session_id else "default") == command.session_id
                and r.id.startswith(target_id)
            ]
            other_session_matches = [
                r for r in all_records
                if (r.context.session_id if r.context and r.context.session_id else "default") != command.session_id
                and r.id.startswith(target_id)
            ]

            if len(session_matches) == 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    task=session_matches[0],
                    matching_tasks=session_matches,
                )
            elif len(session_matches) > 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    matching_tasks=session_matches,
                    error_message=f"Ambiguous task ID prefix '{target_id}' matches {len(session_matches)} tasks in session '{command.session_id}'",
                )
            else:
                if other_session_matches:
                    return TaskResolutionResult(
                        status=ResolutionStatus.UNAUTHORIZED,
                        error_message=f"Task '{target_id}' not found or access denied.",
                    )
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"Task '{target_id}' not found",
                )

        # ------------------------------------------------------------------
        # 2. Implicit targeting (no task_id provided)
        # ------------------------------------------------------------------
        all_records = await service.list_tasks()
        session_records = [
            r for r in all_records
            if (r.context.session_id if r.context and r.context.session_id else "default") == command.session_id
        ]

        if command.action == TaskAction.PAUSE:
            running = [r for r in session_records if r.status == TaskStatus.RUNNING]
            if len(running) == 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    task=running[0],
                    matching_tasks=running,
                )
            elif len(running) > 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    matching_tasks=running,
                    error_message=f"Ambiguous pause request: {len(running)} running tasks in session '{command.session_id}'. Specify task_id.",
                )
            else:
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"No running task found to pause in session '{command.session_id}'",
                )

        if command.action == TaskAction.RESUME:
            paused = [r for r in session_records if r.status == TaskStatus.PAUSED]
            if len(paused) == 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    task=paused[0],
                    matching_tasks=paused,
                )
            elif len(paused) > 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    matching_tasks=paused,
                    error_message=f"Ambiguous resume request: {len(paused)} paused tasks in session '{command.session_id}'. Specify task_id.",
                )
            else:
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"No paused task found to resume in session '{command.session_id}'",
                )

        if command.action == TaskAction.CANCEL:
            active = [r for r in session_records if r.status in (TaskStatus.RUNNING, TaskStatus.PAUSED)]
            if len(active) == 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    task=active[0],
                    matching_tasks=active,
                )
            elif len(active) > 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    matching_tasks=active,
                    error_message=f"Ambiguous cancel request: {len(active)} active tasks in session '{command.session_id}'. Specify task_id.",
                )
            else:
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"No active task found to cancel in session '{command.session_id}'",
                )

        if command.action == TaskAction.STATUS:
            active = [r for r in session_records if r.status in (TaskStatus.RUNNING, TaskStatus.PAUSED)]
            if len(active) == 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    task=active[0],
                    matching_tasks=active,
                )
            elif len(active) > 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    matching_tasks=active,
                    error_message=f"Multiple active tasks in session '{command.session_id}'. Specify task_id.",
                )
            else:
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"No active task found in session '{command.session_id}'",
                )

        if command.action == TaskAction.LIST:
            if command.filter_status:
                matching = [r for r in session_records if r.status == command.filter_status]
            else:
                matching = session_records
            sorted_matching = sorted(matching, key=lambda r: r.created_at, reverse=True)[:10]
            return TaskResolutionResult(
                status=ResolutionStatus.RESOLVED,
                task=sorted_matching[0] if sorted_matching else None,
                matching_tasks=sorted_matching,
            )

        if command.action in (TaskAction.RETRY_STEP, TaskAction.SKIP_STEP):
            active = [r for r in session_records if r.status in (TaskStatus.RUNNING, TaskStatus.PAUSED)]
            if len(active) == 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.RESOLVED,
                    task=active[0],
                    matching_tasks=active,
                )
            elif len(active) > 1:
                return TaskResolutionResult(
                    status=ResolutionStatus.AMBIGUOUS,
                    matching_tasks=active,
                    error_message=f"Multiple active tasks in session '{command.session_id}'. Specify task_id.",
                )
            else:
                return TaskResolutionResult(
                    status=ResolutionStatus.NOT_FOUND,
                    error_message=f"No active task found to {command.action.value} in session '{command.session_id}'",
                )

        return TaskResolutionResult(
            status=ResolutionStatus.NOT_FOUND,
            error_message=f"Cannot resolve task for action {command.action}",
        )

    resolve_async = resolve
