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
        skill_manager: Optional["SkillManager"] = None,
    ) -> None:
        self.retry = retry_policy or RetryPolicy()
        self.rollback = rollback_handler or DefaultCompensation()
        self.skill_manager = skill_manager

    def _get_skill_manager(self):
        """Get or create the skill manager."""
        if self.skill_manager is not None:
            return self.skill_manager
        # Lazy import to avoid circular dependency
        from nova.skills.manager import get_skill_manager
        return get_skill_manager()

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
                
                # Check if result is a tool specification (from ActionNode)
                if isinstance(result, dict) and "tool" in result and "args" in result:
                    tool_name = result["tool"]
                    tool_args = result["args"]
                    skill_mgr = self._get_skill_manager()
                    
                    logger.debug("Executing skill: %s with args: %s", tool_name, tool_args)
                    
                    # Build intent payload for SkillManager
                    intent_payload = {"intent": tool_name}
                    intent_payload.update(tool_args)
                    
                    # Execute through SkillManager (sync call)
                    skill_result = skill_mgr.execute_intent(intent_payload)
                    
                    if skill_result.get("status") == "ok":
                        result = skill_result.get("result")
                    else:
                        # Skill execution failed or not found
                        error_msg = skill_result.get("message", "Skill execution failed")
                        logger.error("Skill %s failed: %s", tool_name, error_msg)
                        raise RuntimeError(f"Skill {tool_name} failed: {error_msg}")
                
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