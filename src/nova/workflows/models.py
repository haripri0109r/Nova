"""
Workflow Engine - core data models.

All models are pure Pydantic data containers.
No business logic, no execution logic, no helper functions.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# =====================================================================
# Enums
# =====================================================================
class WorkflowStatus(str, Enum):
    """Lifecycle of a workflow execution."""
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskStatus(str, Enum):
    """Lifecycle of an individual task inside a workflow."""
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class ExecutionMode(str, Enum):
    """How the workflow engine should execute the plan."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"


class DependencyType(str, Enum):
    """Type of dependency between two tasks."""
    SEQUENTIAL = "sequential"
    PARALLEL = "parallel"
    CONDITIONAL = "conditional"
    JOIN = "join"


class RetryStrategy(str, Enum):
    """Retry policy for a failed task."""
    NONE = "none"
    FIXED = "fixed"
    EXPONENTIAL = "exponential"


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Value objects / policies
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class RetryPolicy(BaseModel):
    """Retry configuration for a single task."""
    strategy: RetryStrategy = RetryStrategy.NONE
    max_attempts: int = 1
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True


class WorkflowMetadata(BaseModel):
    """Extensible, versioned metadata attached to a workflow definition or execution."""
    version: int = 1
    tags: Dict[str, str] = Field(default_factory=dict)
    labels: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Core workflow definition models
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class WorkflowDependency(BaseModel):
    """Describes a dependency between two tasks."""
    upstream_task_id: str
    downstream_task_id: str
    dependency_type: DependencyType = DependencyType.SEQUENTIAL
    condition: Optional[str] = None


class WorkflowTask(BaseModel):
    """Single unit of work inside a workflow."""
    task_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    description: Optional[str] = None
    skill_name: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 30
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    upstream_task_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStep(BaseModel):
    """Optional higher-level grouping of tasks that share the same execution mode."""
    step_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    description: Optional[str] = None
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    tasks: List["WorkflowTask"] = Field(default_factory=list)


class WorkflowDefinition(BaseModel):
    """
    Mutable workflow definition - built by the Planner, then frozen into a WorkflowPlan.
    """
    workflow_id: str = Field(default_factory=lambda: uuid4().hex)
    name: str
    description: Optional[str] = None
    tasks: List["WorkflowTask"] = Field(default_factory=list)
    steps: List["WorkflowStep"] = Field(default_factory=list)
    metadata: "WorkflowMetadata" = Field(default_factory=WorkflowMetadata)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    workflow_version: int = 1


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Execution-time models
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class WorkflowContext(BaseModel):
    """Runtime context passed to every task execution."""
    workflow_id: str
    execution_id: str
    parent_workflow_id: Optional[str] = None
    session_id: str = ""
    trace_id: str = ""
    user_id: Optional[str] = None
    variables: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class WorkflowExecution(BaseModel):
    """Runtime representation of a workflow instance."""
    execution_id: str = Field(default_factory=lambda: uuid4().hex)
    workflow_id: str
    status: WorkflowStatus = WorkflowStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: Optional[str] = None
    task_results: Dict[str, "TaskResult"] = Field(default_factory=dict)
    metadata: "WorkflowMetadata" = Field(default_factory=WorkflowMetadata)
    cancelled: bool = False


class TaskResult(BaseModel):
    """Result of a single task execution."""
    task_id: str
    status: TaskStatus = TaskStatus.PENDING
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    execution_time_ms: int = 0
    output: Optional[Any] = None
    error: Optional[str] = None
    retry_count: int = 0


class WorkflowResult(BaseModel):
    """Result of a completed workflow execution."""
    workflow_id: str
    execution_id: str
    status: WorkflowStatus = WorkflowStatus.COMPLETED
    started_at: datetime
    completed_at: Optional[datetime] = None
    total_time_ms: int = 0
    task_results: Dict[str, "TaskResult"] = Field(default_factory=dict)
    error: Optional[str] = None
    metadata: "WorkflowMetadata" = Field(default_factory=WorkflowMetadata)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Planning artifacts
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class WorkflowPlan(BaseModel):
    """
    Immutable execution plan produced by the Planner.
    Contains a flat list of tasks with resolved dependencies.
    """
    workflow_id: str
    plan_id: str = Field(default_factory=lambda: uuid4().hex)
    tasks: List["WorkflowTask"] = Field(default_factory=list)
    execution_mode: ExecutionMode = ExecutionMode.SEQUENTIAL
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "frozen": True,
    }


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Validation result
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class ValidationResult(BaseModel):
    """Result of workflow validation."""
    valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Event / statistics models (data only, no logic)
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class WorkflowEvent(BaseModel):
    """Pure data model for workflow lifecycle events."""
    event_id: str = Field(default_factory=lambda: uuid4().hex)
    workflow_id: str
    execution_id: str
    task_id: Optional[str] = None
    event_type: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    payload: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStatistics(BaseModel):
    """Purely informational statistics for a running / completed workflow."""
    total_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    running_tasks: int = 0
    skipped_tasks: int = 0
    cancelled_tasks: int = 0
    progress_percentage: float = 0.0


# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
# Exported symbols
# ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
__all__ = [
    # enums
    "WorkflowStatus",
    "TaskStatus",
    "ExecutionMode",
    "DependencyType",
    "RetryStrategy",
    # value objects / policies
    "RetryPolicy",
    "WorkflowMetadata",
    # core definitions
    "WorkflowDependency",
    "WorkflowTask",
    "WorkflowStep",
    "WorkflowDefinition",
    # execution-time models
    "WorkflowContext",
    "WorkflowExecution",
    "TaskResult",
    "WorkflowResult",
    # planning
    "WorkflowPlan",
    # validation
    "ValidationResult",
    # events / stats
    "WorkflowEvent",
    "WorkflowStatistics",
]