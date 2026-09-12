"""Core data models for the Agent Orchestrator."""
from __future__ import annotations
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4
from pydantic import BaseModel, Field, model_validator
from typing import Literal


from .exceptions import InvalidStateTransitionError


class ActionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    INTERRUPTED = "interrupted"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    CANCELLED = "cancelled"
    COMPLETED = "completed"
    FAILED = "failed"

    def is_terminal(self) -> bool:
        """Return True if this status is terminal (cannot transition further).
        
        NOTE: FAILED is NOT fully terminal — it can transition to PAUSED to allow
        interrupted-step remediation (retry/skip). Only COMPLETED and CANCELLED
        are irreversible.
        """
        return self in (TaskStatus.COMPLETED, TaskStatus.CANCELLED)

    def is_active(self) -> bool:
        """Return True if the task is currently active/in-flight."""
        return self in (TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.PAUSED)

    def can_transition_to(self, target: "TaskStatus") -> bool:
        """Check whether transition to target status is permitted."""
        if self == target:
            return True
        valid_transitions = {
            TaskStatus.PENDING: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
            TaskStatus.RUNNING: {TaskStatus.PAUSED, TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED},
            TaskStatus.PAUSED: {TaskStatus.RUNNING, TaskStatus.CANCELLED},
            TaskStatus.FAILED: {TaskStatus.PAUSED},  # allow FAILED→PAUSED for interrupted-step remediation
            TaskStatus.COMPLETED: set(),
            TaskStatus.CANCELLED: set(),
        }
        return target in valid_transitions.get(self, set())


class TaskPriority(str, Enum):
    """Priority level for task scheduling and execution."""
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"

    @property
    def level(self) -> int:
        levels = {
            TaskPriority.LOW: 1,
            TaskPriority.NORMAL: 2,
            TaskPriority.HIGH: 3,
            TaskPriority.URGENT: 4,
        }
        return levels[self]

    def __lt__(self, other: Any) -> bool:
        if isinstance(other, TaskPriority):
            return self.level < other.level
        return NotImplemented

    def __le__(self, other: Any) -> bool:
        if isinstance(other, TaskPriority):
            return self.level <= other.level
        return NotImplemented

    def __gt__(self, other: Any) -> bool:
        if isinstance(other, TaskPriority):
            return self.level > other.level
        return NotImplemented

    def __ge__(self, other: Any) -> bool:
        if isinstance(other, TaskPriority):
            return self.level >= other.level
        return NotImplemented


class ToolAction(BaseModel):
    """Single action to be executed by a skill."""
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    depends_on: List[int] = Field(default_factory=list)  # indices of previous steps


class TaskStep(BaseModel):
    """Individual executable step within a Task."""
    step_id: str = Field(default_factory=lambda: uuid4().hex)
    step_index: int = 0
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""
    status: ActionStatus = ActionStatus.PENDING
    depends_on: List[int] = Field(default_factory=list)
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 0

    class Config:
        arbitrary_types_allowed = True

    def mark_running(self) -> None:
        """Mark this step as actively executing."""
        self.status = ActionStatus.RUNNING
        self.started_at = datetime.utcnow()
        self.completed_at = None

    def mark_success(self, result: Any = None, execution_time_ms: int = 0) -> None:
        """Mark this step as successfully completed."""
        self.status = ActionStatus.SUCCESS
        self.result = result
        self.error = None
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_failed(self, error: str, execution_time_ms: int = 0) -> None:
        """Mark this step as failed."""
        self.status = ActionStatus.FAILED
        self.error = error
        self.result = None
        self.execution_time_ms = execution_time_ms
        self.completed_at = datetime.utcnow()

    def mark_skipped(self, reason: Optional[str] = None) -> None:
        """Mark this step as skipped."""
        self.status = ActionStatus.SKIPPED
        self.error = reason
        self.result = None
        self.completed_at = datetime.utcnow()

    def mark_interrupted(self, error: Optional[str] = None, reason: Optional[str] = None) -> None:
        """Mark this step as interrupted (outcome unknown). Valid only from RUNNING."""
        if self.status != ActionStatus.RUNNING:
            from .exceptions import InvalidStateTransitionError
            raise InvalidStateTransitionError(
                from_state=self.status.value,
                to_state=ActionStatus.INTERRUPTED.value,
                task_id=self.step_id,
            )
        self.status = ActionStatus.INTERRUPTED
        self.error = error or reason or "Process terminated during execution"
        self.completed_at = datetime.utcnow()

    def to_pending(self) -> None:
        """Reset step to PENDING state for retry preparation."""
        self.status = ActionStatus.PENDING
        self.error = None
        self.result = None
        self.started_at = None
        self.completed_at = None

    def to_tool_action(self) -> ToolAction:
        """Convert step to ToolAction for executor compatibility."""
        return ToolAction(
            tool=self.tool,
            parameters=self.parameters,
            description=self.description,
            depends_on=self.depends_on,
        )

    @classmethod
    def from_tool_action(cls, action: ToolAction, step_index: int = 0) -> "TaskStep":
        """Construct a TaskStep from a ToolAction."""
        return cls(
            step_index=step_index,
            tool=action.tool,
            parameters=action.parameters,
            description=action.description,
            depends_on=action.depends_on,
        )


class ActionResult(BaseModel):
    """Result of a single skill execution."""
    tool: str
    success: bool
    execution_time_ms: int = 0
    result: Optional[Any] = None
    error: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class ExecutionRequest(BaseModel):
    """Input received from the LLM Engine."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)
    session_id: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Result returned to the Brain Engine."""
    success: bool
    message: str
    results: List[ActionResult] = Field(default_factory=list)
    execution_id: str = Field(default_factory=lambda: __import__('uuid').uuid4().hex)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None


class Task(BaseModel):
    """Canonical domain model for a multi-step Task."""
    id: str = Field(default_factory=lambda: uuid4().hex)
    session_id: str
    title: str = ""
    description: str = ""
    status: TaskStatus = TaskStatus.PENDING
    priority: TaskPriority = TaskPriority.NORMAL
    steps: List[TaskStep] = Field(default_factory=list)
    current_step_index: int = -1
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    max_steps: Optional[int] = None
    wall_clock_timeout_seconds: Optional[int] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    plan: Optional["ExecutionPlan"] = None
    context: Optional["ExecutionContext"] = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def current_step(self) -> Optional[TaskStep]:
        """Return the current step being executed, or None."""
        if 0 <= self.current_step_index < len(self.steps):
            return self.steps[self.current_step_index]
        return None

    def add_step(self, step: TaskStep) -> None:
        """Append a step and ensure sequential indexing and plan synchronization."""
        if step.step_index == 0 and len(self.steps) > 0:
            step.step_index = len(self.steps)
        self.steps.append(step)
        if self.plan is not None:
            self.plan.actions = [s.to_tool_action() for s in self.steps]
        self.updated_at = datetime.utcnow()

    def transition_to(self, target: TaskStatus) -> None:
        """Validate and apply a status transition."""
        if not self.status.can_transition_to(target):
            raise InvalidStateTransitionError(
                from_state=self.status.value,
                to_state=target.value,
                task_id=self.id,
            )
        self.status = target
        now = datetime.utcnow()
        self.updated_at = now
        if target == TaskStatus.RUNNING and self.started_at is None:
            self.started_at = now
        elif target.is_terminal():
            self.completed_at = now

    def start(self) -> None:
        """Transition task to RUNNING."""
        self.transition_to(TaskStatus.RUNNING)

    def pause(self) -> None:
        """Transition task to PAUSED."""
        self.transition_to(TaskStatus.PAUSED)

    def resume(self) -> None:
        """Resume task back to RUNNING."""
        self.transition_to(TaskStatus.RUNNING)

    def complete(self) -> None:
        """Transition task to COMPLETED."""
        self.transition_to(TaskStatus.COMPLETED)

    def cancel(self, reason: Optional[str] = None) -> None:
        """Transition task to CANCELLED."""
        if reason:
            self.metadata["cancel_reason"] = reason
        self.transition_to(TaskStatus.CANCELLED)

    def fail(self, error: str) -> None:
        """Transition task to FAILED with error message."""
        self.error = error
        self.transition_to(TaskStatus.FAILED)

    def to_record(self) -> "TaskRecord":
        """Convert domain Task to persisted TaskRecord preserving all state."""
        plan = ExecutionPlan(
            steps=[step.to_tool_action() for step in self.steps],
            execution_mode=self.plan.execution_mode if self.plan else "sequential",
            description=self.plan.description if self.plan else self.description,
            metadata=self.metadata,
            timeout_seconds=self.plan.timeout_seconds if self.plan else 300,
        )
        context = self.context or ExecutionContext(
            session_id=self.session_id,
            execution_id=self.id,
            task_id=self.id,
            status=self.status,
            current_step=self.current_step_index,
            metadata=self.metadata,
            max_steps=self.max_steps,
            wall_clock_timeout_seconds=self.wall_clock_timeout_seconds,
        )
        # Ensure context.step_results reflects completed steps
        for step in self.steps:
            if step.status in (ActionStatus.SUCCESS, ActionStatus.FAILED):
                if not any(r.get("step") == step.step_index for r in context.step_results):
                    context.add_step_result(
                        step_index=step.step_index,
                        tool=step.tool,
                        success=(step.status == ActionStatus.SUCCESS),
                        result=step.result if step.status == ActionStatus.SUCCESS else step.error,
                    )
        return TaskRecord(
            id=self.id,
            plan=plan,
            context=context,
            status=self.status,
            created_at=self.created_at,
            updated_at=self.updated_at,
            current_step=self.current_step_index,
            max_steps=self.max_steps,
            wall_clock_timeout_seconds=self.wall_clock_timeout_seconds,
            title=self.title,
            description=self.description,
            priority=self.priority,
            steps=self.steps,
            started_at=self.started_at,
            completed_at=self.completed_at,
            error=self.error,
            metadata=self.metadata,
        )

    @classmethod
    def from_record(cls, record: "TaskRecord", title: str = "", description: str = "") -> "Task":
        """Construct domain Task from persisted TaskRecord without data loss."""
        if record.steps:
            steps = record.steps
        else:
            steps = [
                TaskStep.from_tool_action(action, step_index=i)
                for i, action in enumerate(record.plan.steps)
            ]
            for res in record.context.step_results:
                s_idx = res.get("step")
                if s_idx is not None and 0 <= s_idx < len(steps):
                    if res.get("success"):
                        steps[s_idx].status = ActionStatus.SUCCESS
                        steps[s_idx].result = res.get("result")
                    else:
                        steps[s_idx].status = ActionStatus.FAILED
                        steps[s_idx].error = str(res.get("result") or "")

        return cls(
            id=record.id,
            session_id=record.context.session_id,
            title=record.title or title,
            description=record.description or description,
            status=record.status,
            priority=record.priority,
            steps=steps,
            current_step_index=record.current_step,
            created_at=record.created_at,
            updated_at=record.updated_at,
            started_at=record.started_at,
            completed_at=record.completed_at,
            max_steps=record.max_steps,
            wall_clock_timeout_seconds=record.wall_clock_timeout_seconds,
            metadata=record.metadata if record.metadata else record.context.metadata,
            error=record.error,
            plan=record.plan,
            context=record.context,
        )


class TaskRecord(BaseModel):
    """Persisted task record for durable multi-step execution."""
    id: str = Field(default_factory=lambda: uuid4().hex)
    plan: "ExecutionPlan"
    context: "ExecutionContext"
    status: TaskStatus = TaskStatus.RUNNING
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    current_step: int = -1
    max_steps: Optional[int] = None
    wall_clock_timeout_seconds: Optional[int] = None
    title: str = ""
    description: str = ""
    priority: TaskPriority = TaskPriority.NORMAL
    steps: List[TaskStep] = Field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    def to_task(self, title: str = "", description: str = "") -> Task:
        """Convert persisted record to canonical Task domain model."""
        return Task.from_record(self, title=title, description=description)


class SkillContext(BaseModel):
    """Runtime context passed to skills."""
    session_id: str
    execution_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    user_id: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class SkillDefinition(BaseModel):
    """Metadata about a registered skill."""
    name: str
    description: str
    required_permissions: List[str] = Field(default_factory=list)
    parameters_schema: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 30
    retry_policy: Optional[Dict[str, Any]] = None


class ExecutionPlan(BaseModel):
    """Execution plan containing a sequence of actions."""
    model_config = {"populate_by_name": True}

    actions: List[ToolAction] = Field(default_factory=list, alias="steps")
    execution_mode: Literal["sequential", "parallel"] = "sequential"
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 300

    # Backward compatibility: accept 'intents' or 'actions' as alias for 'steps'
    @model_validator(mode='before')
    @classmethod
    def _accept_intents_alias(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if 'intents' in data and 'actions' not in data and 'steps' not in data:
                data['steps'] = data.pop('intents')
            elif 'actions' in data and 'steps' not in data:
                data['steps'] = data.pop('actions')
        return data

    @property
    def steps(self) -> List[ToolAction]:
        """Alias for actions to maintain compatibility with Brain models."""
        return self.actions


class ValidationResult(BaseModel):
    """Result of validation."""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    
    def __bool__(self):
        return self.valid
    
    def __str__(self):
        return f"ValidationResult(valid={self.valid}, errors={self.errors})"


class ExecutionContext(BaseModel):
    """Runtime context passed between steps in a multi-step plan."""
    session_id: str
    execution_id: str
    task_id: Optional[str] = None
    status: TaskStatus = TaskStatus.RUNNING
    current_step: int = -1
    step_results: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    max_steps: Optional[int] = None
    wall_clock_timeout_seconds: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    def add_step_result(self, step_index: int, tool: str, success: bool, result: Any) -> None:
        """Record the result of a completed step."""
        self.step_results.append({
            "step": step_index,
            "tool": tool,
            "success": success,
            "result": result,
        })
        self.updated_at = datetime.utcnow()
    
    def get_compact_context(self) -> Dict[str, Any]:
        """Return a compact representation for LLM context."""
        return {
            "completed_steps": len(self.step_results),
            "metadata": self.metadata,
        }


class TaskAction(str, Enum):
    """Actions supported by task management commands."""
    PAUSE = "pause"
    RESUME = "resume"
    CANCEL = "cancel"

    RETRY_STEP = "retry_step"
    SKIP_STEP = "skip_step"

    STATUS = "status"
    LIST = "list"


class TaskCommand(BaseModel):
    """Structured, deterministic representation of a user task-management command."""
    action: TaskAction
    task_id: Optional[str] = None
    step_index: Optional[int] = None
    filter_status: Optional[TaskStatus] = None
    session_id: str = "default"
    # High-risk retry confirmation fields
    confirmed: bool = False
    confirmation_token: Optional[str] = None

    @classmethod
    def from_entities(
        cls,
        entities: Dict[str, Any],
        session_id: str = "default",
        default_action: Optional[TaskAction] = None,
    ) -> "TaskCommand":
        """Construct TaskCommand from intent entity dictionary."""
        act_val = entities.get("action")
        if act_val:
            action = TaskAction(act_val)
        elif default_action:
            action = default_action
        else:
            raise ValueError("TaskCommand requires an action")

        task_id = entities.get("task_id")
        step_index = entities.get("step_index")
        if step_index is not None:
            try:
                step_index = int(step_index)
            except (ValueError, TypeError):
                step_index = None

        filter_status = entities.get("filter_status")
        if filter_status and isinstance(filter_status, str):
            try:
                filter_status = TaskStatus(filter_status)
            except ValueError:
                filter_status = None

        confirmed = bool(entities.get("confirmed", False))
        confirmation_token = entities.get("confirmation_token")

        return cls(
            action=action,
            task_id=task_id,
            step_index=step_index,
            filter_status=filter_status,
            session_id=session_id,
            confirmed=confirmed,
            confirmation_token=confirmation_token,
        )