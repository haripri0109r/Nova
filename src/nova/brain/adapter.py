"""
Adapter / mapper layer – converts Brain internal models to Agent public models.

This keeps the Brain Engine free of Agent‑specific construction logic.
"""
from __future__ import annotations

from typing import Optional, List
from ..agent.models import ExecutionRequest, ToolAction, ExecutionPlan as AgentExecutionPlan
from .models import IntentResult, ExecutionPlan, PlanStep


def intent_to_execution_request(
    intent: IntentResult,
    session_id: Optional[str] = None,
) -> ExecutionRequest:
    """
    Translate a classified ``IntentResult`` into an ``ExecutionRequest`` that the
    Agent Orchestrator can execute.

    The mapping is intentionally simple – one ``ToolAction`` per intent.
    Extend here if a single intent should fan‑out to multiple actions.
    """
    tool_name = intent.category.value
    # Special case: screen_read intent maps to screen.read tool
    if intent.category.value == "screen_read":
        tool_name = "screen.read"
    parameters = intent.entities or {}
    return ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=[ToolAction(tool=tool_name, parameters=parameters)],
    )


def execution_plan_to_execution_request(
    plan: ExecutionPlan,
    session_id: Optional[str] = None,
) -> ExecutionRequest:
    """
    Convert a Brain ``ExecutionPlan`` (multi-step) into an ``ExecutionRequest``.
    """
    actions = [
        ToolAction(tool=step.tool, parameters=step.parameters, depends_on=step.depends_on)
        for step in plan.steps
    ]
    return ExecutionRequest(
        requires_execution=True,
        response_text="",
        actions=actions,
        session_id=session_id,
    )


def execution_request_to_plan_steps(request: ExecutionRequest):
    """
    Convert an ``ExecutionRequest`` into a list of ``ToolAction`` suitable for the
    Brain's ``ExecutionPlan`` response model.
    """
    return [
        ToolAction(tool=action.tool, parameters=action.parameters)
        for action in request.actions
    ]


def plan_steps_to_plan_step(request: ExecutionRequest) -> List[PlanStep]:
    """
    Convert an ``ExecutionRequest`` into a list of ``PlanStep`` for Brain's ExecutionPlan.
    """
    return [
        PlanStep(tool=action.tool, parameters=action.parameters, depends_on=action.depends_on)
        for action in request.actions
    ]