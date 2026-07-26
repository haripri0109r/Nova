"""
NodeExecutor – executes a workflow node with retry, timeout, rollback support.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

from .nodes import Node
from .retry import RetryPolicy
from .rollback import DefaultCompensation, CompensationHandler

logger = logging.getLogger("nova.workflows.executor")


class NodeExecutor:
    """
    Executes a single workflow node with retry, timeout and rollback support.
    """

    def __init__(
        self,
        retry_policy: Optional[RetryPolicy] = None,
        rollback_handler: Optional[CompensationHandler] = None,
    ) -> None:
        self.retry = retry_policy or RetryPolicy()
        self.rollback = rollback_handler or DefaultCompensation()

    async def execute(self, node: "Node", ctx: Dict[str, Any], executed_nodes: Optional[List["Node"]] = None) -> Any:
        """
        Execute a single node with retry, timeout and rollback support.
        Returns the node's execute result (could be bool, dict, etc.).
        """
        executed = executed_nodes or []
        retry_policy = getattr(node, "retry_policy", None) or self.retry

        attempt = 0
        while True:
            try:
                result = await node.execute(ctx)
                return result
            except Exception as exc:
                attempt += 1
                if not retry_policy.should_retry_attempt(attempt, exc):
                    if getattr(node, "compensation", None):
                        await self.rollback.compensate(ctx, executed + [node])
                    raise
                await retry_policy.wait(attempt)


def get_node_executor() -> NodeExecutor:
    """Factory for a default NodeExecutor."""
    return NodeExecutor()