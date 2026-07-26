"""
Workflow node definitions.
"""
from __future__ import annotations
import asyncio
import uuid
from abc import ABC, abstractmethod
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Callable, Awaitable
from pydantic import BaseModel, Field, ConfigDict


class NodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class Node(BaseModel, ABC):
    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    description: str = ""
    status: NodeStatus = NodeStatus.PENDING
    retry_policy: Optional["RetryPolicy"] = None
    compensation: Optional["CompensationHandler"] = None
    timeout: float = 30.0  # seconds
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error: Optional[str] = None

    @abstractmethod
    async def execute(self, context: Dict[str, Any]) -> Any:
        """Execute the node logic. Must be implemented by subclasses."""
        ...

    def mark_running(self) -> None:
        self.status = NodeStatus.RUNNING
        self.started_at = datetime.utcnow()

    def mark_completed(self, result: Any = None) -> None:
        self.status = NodeStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        self.metadata["result"] = result

    def mark_failed(self, error: str) -> None:
        self.status = NodeStatus.FAILED
        self.completed_at = datetime.utcnow()
        self.error = error

    def mark_skipped(self) -> None:
        self.status = NodeStatus.SKIPPED
        self.completed_at = datetime.utcnow()


class ActionNode(Node):
    """
    Executes a callable (sync or async) with provided arguments.
    """
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    callable: Optional[Callable[..., Any]] = None

    async def execute(self, context: Dict[str, Any]) -> Any:
        # If a callable is provided, invoke it with args
        if self.callable:
            if asyncio.iscoroutinefunction(self.callable):
                return await self.callable(**self.args)
            else:
                return self.callable(**self.args)
        # Otherwise, this node represents a controller action identified by `tool`
        # The actual execution is delegated to the ToolExecutor via the workflow engine.
        # Return a marker indicating the tool to invoke.
        return {"tool": self.tool, "args": self.args}


class ConditionNode(Node):
    """
    Evaluates a condition; if true follows true_branch, else false_branch.
    """
    condition: str
    true_branch: List["Node"] = Field(default_factory=list)
    false_branch: List["Node"] = Field(default_factory=list)

    async def execute(self, context: Dict[str, Any]) -> bool:
        # Evaluate the condition expression string safely
        from .conditions import ExpressionCondition
        cond = ExpressionCondition(expression=self.condition)
        return await cond.evaluate(context)


class ParallelNode(Node):
    """
    Executes child nodes in parallel.
    """
    children: List["Node"] = Field(default_factory=list)

    async def execute(self, context: Dict[str, Any]) -> List[Any]:
        tasks = [child.execute(context) for child in self.children]
        return await asyncio.gather(*tasks)


class LoopNode(Node):
    """
    Repeats child node(s) while condition holds.
    """
    condition: str
    child: "Node"
    max_iterations: int = 100

    async def execute(self, context: Dict[str, Any]) -> List[Any]:
        results = []
        from .conditions import ExpressionCondition
        cond = ExpressionCondition(expression=self.condition)
        for i in range(self.max_iterations):
            if not await cond.evaluate(context):
                break
            result = await self.child.execute(context)
            results.append(result)
        return results


# Rebuild models after all forward references are resolved
from .retry import RetryPolicy  # noqa: E402
from .rollback import CompensationHandler  # noqa: E402
from .conditions import Condition  # noqa: E402

ActionNode.model_rebuild()
ConditionNode.model_rebuild()
ParallelNode.model_rebuild()
LoopNode.model_rebuild()


class StartNode(Node):
    """Workflow start marker."""

    async def execute(self, context: Dict[str, Any]) -> None:
        self.mark_completed()
        return None


class EndNode(Node):
    """Workflow end marker."""

    async def execute(self, context: Dict[str, Any]) -> None:
        self.mark_completed()
        return None


class DelayNode(Node):
    """Delay execution for a configured number of seconds."""
    seconds: float = 1.0

    async def execute(self, context: Dict[str, Any]) -> None:
        await asyncio.sleep(self.seconds)
        self.mark_completed()
        return None


class MergeNode(Node):
    """Merge multiple incoming branches – no logic, just a join point."""

    async def execute(self, context: Dict[str, Any]) -> None:
        self.mark_completed()
        return None


class EventNode(Node):
    """Emit an event (placeholder)."""
    event_name: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)

    async def execute(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # In a real engine this would publish to EventBus
        self.mark_completed()
        return {"event": self.event_name, "payload": self.payload}


class CompensationNode(Node):
    """Compensation handler for rollback."""
    compensation_action: str = ""

    async def execute(self, context: Dict[str, Any]) -> None:
        # Placeholder: actual compensation logic handled by RollbackManager
        self.mark_completed()
        return None