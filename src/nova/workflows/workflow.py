"""
Workflow definitions – core data structures for workflows.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, ConfigDict
import uuid

from .models import WorkflowStatus


@dataclass
class WorkflowEdge:
    from_node: str
    to_node: str
    condition: Optional[str] = None  # optional expression to decide edge


class Workflow(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    name: str
    version: str = "1.0"
    description: str = ""
    status: WorkflowStatus = Field(default=WorkflowStatus.PENDING)
    nodes: List["Node"] = Field(default_factory=list)
    edges: List[WorkflowEdge] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_node(self, node: "Node") -> None:
        self.nodes.append(node)
        self.updated_at = datetime.utcnow()

    def add_edge(self, from_node: str, to_node: str, condition: Optional[str] = None) -> None:
        self.edges.append(WorkflowEdge(from_node=from_node, to_node=to_node, condition=condition))
        self.updated_at = datetime.utcnow()


# Rebuild model after Node class is defined
from .nodes import Node  # noqa: E402
Workflow.model_rebuild()