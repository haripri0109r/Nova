"""
WorkflowEngine – orchestrates execution of a Workflow DAG.
"""
from __future__ import annotations
import asyncio
import copy
import logging
import uuid
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
            # Build name to id mapping
            name_to_id = {node.name: node.id for node in workflow.nodes}
            id_to_node = {node.id: node for node in workflow.nodes}
            
            # Validate all edge references exist
            self._validate_edge_references(workflow, name_to_id)
            
            # Build adjacency and indegree using node ids
            adj: Dict[str, List[str]] = defaultdict(list)
            indegree: Dict[str, int] = {node.id: 0 for node in workflow.nodes}
            for edge in workflow.edges:
                # Skip conditional edges; they are handled by ConditionNode logic
                if edge.condition is not None:
                    continue
                # Resolve names to ids
                frm = name_to_id[edge.from_node]
                to = name_to_id[edge.to_node]
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
                        succ_node = id_to_node.get(succ_id)
                        if succ_node:
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

    def _validate_edge_references(self, workflow: Workflow, name_to_id: Dict[str, str]) -> None:
        """
        Validate that all edge references point to existing nodes.
        Raises ValueError with clear message if any reference is invalid.
        """
        existing_names = set(name_to_id.keys())
        existing_ids = set(name_to_id.values())
        
        for edge in workflow.edges:
            # Skip conditional edges; they are handled by ConditionNode logic
            if edge.condition is not None:
                continue
            
            # Check from_node
            if edge.from_node not in existing_names and edge.from_node not in existing_ids:
                raise ValueError(
                    f"Workflow edge references unknown node '{edge.from_node}' "
                    f"(available: {sorted(existing_names)})"
                )
            
            # Check to_node
            if edge.to_node not in existing_names and edge.to_node not in existing_ids:
                raise ValueError(
                    f"Workflow edge references unknown node '{edge.to_node}' "
                    f"(available: {sorted(existing_names)})"
                )

    class _WorkflowTask(str):
        """A workflow ID string that is also awaitable."""
        def __new__(cls, workflow_id: str, task: asyncio.Task):
            obj = str.__new__(cls, workflow_id)
            obj._task = task
            return obj
        
        def __await__(self):
            return self._task.__await__()
        
        def result(self):
            return self._task.result()

    def run_workflow(self, workflow: Workflow, *, context: Optional[Dict[str, Any]] = None, **kwargs: Any) -> "_WorkflowTask":
        """
        Execute a workflow to completion and return its ID.
        The workflow runs in the background; this method returns immediately with the workflow ID.
        The returned object is both a string (workflow ID) and awaitable.
        """
        # Clone the workflow to allow concurrent runs of the same workflow definition
        workflow_copy = copy.deepcopy(workflow)
        workflow_copy.id = uuid.uuid4().hex  # Generate new unique ID
        workflow_copy.status = WorkflowStatus.RUNNING
        self._workflow_status[workflow_copy.id] = WorkflowStatus.RUNNING
        # schedule the workflow execution in the background
        task = asyncio.create_task(self.run(workflow_copy, initial_context=context))
        return self._WorkflowTask(workflow_copy.id, task)

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
            self._workflow_status[workflow_id] = WorkflowStatus.PAUSED

    async def resume(self, workflow_id: str) -> None:
        wf = self._running_workflows.get(workflow_id)
        if wf and wf.status == WorkflowStatus.PAUSED:
            wf.status = WorkflowStatus.RUNNING
            self._workflow_status[workflow_id] = WorkflowStatus.RUNNING
            # could resume from where left off – simplified not implemented

    async def cancel(self, workflow_id: str) -> None:
        """Cancel a running workflow."""
        wf = self._running_workflows.get(workflow_id)
        if wf:
            wf.status = WorkflowStatus.CANCELLED
            self._workflow_status[workflow_id] = WorkflowStatus.CANCELLED
            self._running_workflows.pop(workflow_id, None)


# Singleton accessor
_engine_instance: Optional[WorkflowEngine] = None


def get_workflow_engine() -> WorkflowEngine:
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = WorkflowEngine()
    return _engine_instance