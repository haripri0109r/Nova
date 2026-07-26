"""
Rollback / compensation handling for workflow failures.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Callable, Awaitable, TYPE_CHECKING
from pydantic import BaseModel, ConfigDict
import asyncio

if TYPE_CHECKING:
    from .nodes import Node


class CompensationHandler(ABC, BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def compensate(self, context: Dict[str, Any], executed_nodes: List["Node"]) -> None:
        """
        Perform compensating actions for already executed nodes.
        """
        ...


class DefaultCompensation(CompensationHandler):
    """
    Default compensation that calls each node's compensation callable if provided.
    """
    async def compensate(self, context: Dict[str, Any], executed_nodes: List["Node"]) -> None:
        for node in reversed(executed_nodes):
            if node.compensation and callable(node.compensation):
                try:
                    if asyncio.iscoroutinefunction(node.compensation):
                        await node.compensation(context, node)
                    else:
                        node.compensation(context, node)
                except Exception:
                    # log but continue
                    pass


class RollbackManager:
    """Manages rollback using a compensation handler."""

    def __init__(self, handler: Optional[CompensationHandler] = None) -> None:
        self.handler = handler or DefaultCompensation()

    async def compensate(self, context: Dict[str, Any], executed_nodes: List["Node"]) -> None:
        await self.handler.compensate(context, executed_nodes)