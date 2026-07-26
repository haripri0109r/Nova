"""
WorkflowEngine – orchestrates execution of a Workflow DAG.
"""
from __future__ import annotations
import asyncio
import logging
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set

from .workflow import Workflow, WorkflowStatus
from .nodes import Node, NodeStatus, ConditionNode
from .executor import NodeExecutor, get_node_executor

logger = logging.getLogger("nova.workflows.engine")


class WorkflowEngine:
    """
    Executes a Workflow DAG respecting dependencies, parallelism, conditions, loops.
    """
    _instances: List["WorkflowEngine"] = []

    def __init__(
        self,
        node_executor: Optional[NodeExecutor] = None,
    ) -> None:
        self.executor = node_executor or get_node_executor()
        self._running_workflows: Dict[str, Workflow] = {}
        self._workflow_status: Dict[str, WorkflowStatus] = {}
        self._started = False

    async def run(self, workflow: Workflow, initial_context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> Dict[str, Any]:
        """
        Execute a workflow to completion.
        Returns final context with results.
        """
        if workflow.id in self._running_workflows:
            raise RuntimeError(f"Workflow {workflow.id} already running")

        workflow.status = WorkflowStatus.RUNNING
        self._running_workflows[workflow.id] = workflow
        # allow extra context via kwargs
        extra_context = kwargs.get("context") or {}
        context = (initial_context or {})
        context.update(extra_context)
        executed_nodes: List["Node"] = []

        try:
            # Build adjacency and indegree
            adj: Dict[str, List[str]] = defaultdict(list)
            indegree: Dict[str, int] = {node.id: 0 for node in workflow.nodes}
            for edge in workflow.edges:
                # Skip conditional edges; they are handled by ConditionNode logic
                if edge.condition is not None:
                    continue
                frm, to = edge.from_node, edge.to_node
                adj[frm].append(to)
                indegree[to] += 1

            # Queue of ready nodes (indegree == 0)
            ready = deque([node for node in workflow.nodes if indegree[node.id] == 0])

            while ready:
                node = ready.popleft()
                if node.status == NodeStatus.SKIPPED:
                    continue
                # Infer node type from class name
                node_type = node.__class__.__name__.replace('Node', '').lower()
                # For ConditionNode, we may need to decide branch
                if node_type == "condition":
                    result = await self.executor.execute(node, context, executed_nodes)
                    # Determine which branch to enable
                    if isinstance(node, ConditionNode):
                        branch = node.true_branch if result else node.false_branch
                        for child in branch:
                            ready.append(child)
                    executed_nodes.append(node)
                    continue

                # Execute regular node
                try:
                    result = await self.executor.execute(node, context, executed_nodes)
                    # store result in context for later nodes
                    context[f"{node.id}_result"] = result.get("output") if isinstance(result, dict) else result
                except Exception as exc:
                    logger.error("Node %s failed: %s", node.name, exc)
                    workflow.status = WorkflowStatus.FAILED
                    raise

                executed_nodes.append(node)

                # Decrease indegree of successors
                for succ_id in adj[node.id]:
                    indegree[succ_id] -= 1
                    if indegree[succ_id] == 0:
                        # find node object
                        succ_node = next(n for n in workflow.nodes if n.id == succ_id)
                        ready.append(succ_node)

            workflow.status = WorkflowStatus.COMPLETED
            self._workflow_status[workflow.id] = workflow.status
            return context

        except Exception as exc:
            workflow.status = WorkflowStatus.FAILED
            self._workflow_status[workflow.id] = workflow.status
            raise
        finally:
            self._running_workflows.pop(workflow.id, None)

    def run_workflow(self, workflow: Workflow, *, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> str:
        """
        Execute a workflow to completion and return its ID.
        The workflow runs in the background; this method returns immediately with the workflow ID.
        """
        # schedule the workflow execution in the background
        asyncio.create_task(self.run(workflow, initial_context=context))
        return workflow.id

    def get_workflow_status(self, workflow_id: str) -> Dict[str, str]:
        """
        Retrieve the current status of a workflow.
        Returns a dict with a 'status' key.
        """
        status = self._workflow_status.get(workflow_id, WorkflowStatus.PENDING)
        return {"status": status.value}

    async def start(self) -> None:
        """
        Initialize the engine and any background resources.
        """
        logger.info("WorkflowEngine starting")
        # Initialize any background tasks or resources here if needed.
        # For now, just mark as started.
        self._started = True
        logger.info("WorkflowEngine started")

    async def stop(self) -> None:
        """
        Stop the engine and clean up resources.
        """
        logger.info("WorkflowEngine stopping")
        # Cancel any running workflows
        for wf in list(self._running_workflows.values()):
            wf.status = WorkflowStatus.CANCELLED
        self._running_workflows.clear()
        self._started = False
        logger.info("WorkflowEngine stopped")

    async def pause(self, workflow_id: str) -> None:
        wf = self._running_workflows.get(workflow_id)
        if wf:
            wf.status = WorkflowStatus.PAUSED

    async def resume(self, workflow_id: str) -> None:
        wf = self._running_workflows.get(workflow_id)
        if wf and wf.status == WorkflowStatus.PAUSED:
            wf.status = WorkflowStatus.RUNNING
            # could resume from where left off – simplified not implemented


# Singleton accessor
_engine_instance: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = WorkflowEngine()
    return _engine_instance