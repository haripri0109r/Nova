"""Workflow data models."""
from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field, ConfigDict


class WorkflowStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkflowNodeStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# Alias for backward compatibility
NodeStatus = WorkflowNodeStatus


class WorkflowEdge(BaseModel):
    model_config = ConfigDict(extra="allow")
    from_node: str
    to_node: str
    condition: Optional[str] = None


class WorkflowNode(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    type: str
    config: dict = {}
    status: str = "pending"
    retry_policy: Optional[dict] = None
    timeout: Optional[float] = None
    compensation: Optional[dict] = None


class Workflow(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str = "1.0"
    description: str = ""
    status: str = Field(default=WorkflowStatus.PENDING.value)
    nodes: List[Dict] = []
    edges: List[Dict] = []
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_node(self, node: dict) -> None:
        self.nodes.append(node)
        self.updated_at = datetime.utcnow()

    def add_edge(self, from_node: str, to_node: str, condition: Optional[str] = None) -> None:
        self.edges.append({"from_node": from_node, "to_node": to_node, "condition": condition})
        self.updated_at = datetime.utcnow()


class WorkflowContext(BaseModel):
    variables: Dict[str, Any] = {}
    outputs: Dict[str, Any] = {}
    env: Dict[str, str] = {}
    temp: Dict[str, Any] = {}


class WorkflowExecution(BaseModel):
    workflow_id: str
    workflow_name: str
    status: str = "pending"
    context: dict = {}
    started_at: datetime
    finished_at: Optional[datetime] = None
    node_results: dict = {}


class ExecutionResult(BaseModel):
    node_id: str
    success: bool
    output: Any = None
    error: Optional[str] = None
    started_at: datetime
    finished_at: Optional[datetime] = None