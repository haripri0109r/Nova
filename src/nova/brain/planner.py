"""
Planner – LLM-based multi-step plan generation.

Takes user text and classified intent, produces an ExecutionPlan with multiple PlanSteps.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from .models import (
    IntentResult,
    ExecutionPlan,
    PlanStep,
)
from nova.llm.manager import get_llm_manager
from ..agent.models import ToolAction
from ..skills.registry import registry as skill_registry

logger = logging.getLogger("nova.brain.planner")


class Planner:
    """
    Generates multi-step execution plans using an LLM.
    
    The planner:
    1. Receives user text and classified intent
    2. Queries available skills from the registry
    3. Asks the LLM to break down the request into executable steps
    4. Validates each step against registered skills
    5. Returns a validated ExecutionPlan
    """

    def __init__(self):
        self._llm_manager = get_llm_manager()
        self._skill_registry = skill_registry

    async def initialize(self) -> bool:
        """Initialize the planner."""
        try:
            await self._llm_manager.initialize()
            return True
        except Exception as e:
            logger.error(f"Planner initialization failed: {e}")
            return False

    async def cleanup(self) -> None:
        """Cleanup planner resources."""
        pass

    def _get_available_tools(self) -> List[Dict[str, Any]]:
        """Get list of available skills/tools from registry."""
        tools = []
        seen_intents = set()
        for skill in self._skill_registry.all():
            if skill.intent not in seen_intents:
                seen_intents.add(skill.intent)
                tools.append({
                    "tool": skill.intent,
                    "description": skill.description,
                    "parameters": getattr(skill, 'parameters_schema', {}),
                })
        return tools

    def _build_planning_prompt(
        self,
        user_text: str,
        intent: IntentResult,
        available_tools: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the prompt for the LLM to generate a plan."""
        tools_json = json.dumps(available_tools, indent=2)
        
        context_str = ""
        if context:
            context_str = f"\nPrevious context:\n{json.dumps(context, indent=2)}\n"

        return f"""You are Nova's planning engine. Break down the user's request into a sequence of executable steps.

User request: "{user_text}"
Classified intent: {intent.category.value} (confidence: {intent.confidence:.2f})
Entities: {json.dumps(intent.entities)}{context_str}

Available tools:
{tools_json}

Generate a JSON plan with the following structure:
{{
  "steps": [
    {{
      "tool": "tool_name",
      "parameters": {{"param": "value"}},
      "depends_on": []  // list of step indices this step depends on
    }}
  ],
  "description": "Brief description of the overall plan"
}}

Rules:
1. Each step must use a tool from the available tools list
2. Parameters must match the tool's parameter schema
3. Use depends_on to express dependencies between steps
4. Keep plans minimal - prefer single steps when possible
5. For screen reading followed by action, use screen.read first, then the action tool
6. Output ONLY the JSON, no extra text

Plan:"""

    async def plan(
        self,
        user_text: str,
        intent: IntentResult,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExecutionPlan:
        """
        Generate an execution plan from user text and intent.
        
        Args:
            user_text: Raw user input
            intent: Classified intent result
            context: Optional execution context from previous steps
            
        Returns:
            ExecutionPlan with validated steps
        """
        available_tools = self._get_available_tools()
        
        # If only one tool matches the intent, return single-step plan directly
        intent_tool = intent.category.value
        if intent_tool == "screen_read":
            intent_tool = "screen.read"
        
        matching_tools = [t for t in available_tools if t["tool"] == intent_tool]
        if len(matching_tools) == 1 and not context:
            # Simple single-step case - no need for LLM
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        tool=intent_tool,
                        parameters=intent.entities or {},
                    )
                ],
                description=f"Execute {intent_tool}",
            )

        # Use LLM for multi-step planning
        prompt = self._build_planning_prompt(user_text, intent, available_tools, context)
        
        try:
            llm_response = await self._llm_manager.process(
                text=prompt,
                context={"extra_context": "Generate a valid JSON plan only."},
            )
            
            # Parse the JSON response
            plan_data = json.loads(llm_response.response_text.strip())
            
            # Validate and convert to PlanStep objects
            validated_steps = []
            for i, step_data in enumerate(plan_data.get("steps", [])):
                tool_name = step_data.get("tool")
                parameters = step_data.get("parameters", {})
                depends_on = step_data.get("depends_on", [])
                
                # Validate tool exists - REJECT if unknown
                if tool_name not in self._skill_registry._skills:
                    raise ValueError(f"Planner generated unknown tool: {tool_name}. Plan rejected.")
                
                # Validate dependencies
                for dep in depends_on:
                    if dep < 0:
                        raise ValueError(f"Step {i} has negative dependency index: {dep}")
                    if dep >= i:
                        raise ValueError(f"Step {i} depends on step {dep} which is not a previous step (forward reference not allowed)")
                    if dep == i:
                        raise ValueError(f"Step {i} has self-dependency")
                
                validated_steps.append(PlanStep(
                    tool=tool_name,
                    parameters=parameters,
                    depends_on=depends_on,
                ))
            
            if not validated_steps:
                # Fallback to single step
                logger.warning("Planner produced no valid steps, falling back to single step")
                return ExecutionPlan(
                    steps=[
                        PlanStep(
                            tool=intent_tool,
                            parameters=intent.entities or {},
                        )
                    ],
                    description=f"Fallback: Execute {intent_tool}",
                )
            
            return ExecutionPlan(
                steps=validated_steps,
                description=plan_data.get("description", "Multi-step plan"),
            )
            
        except json.JSONDecodeError as e:
            logger.error(f"Planner LLM returned invalid JSON: {e}")
            # Fallback to single step
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        tool=intent_tool,
                        parameters=intent.entities or {},
                    )
                ],
                description=f"Fallback: Execute {intent_tool}",
            )
        except ValueError:
            # Re-raise validation errors (unknown tool, invalid dependencies)
            raise
        except Exception as e:
            logger.error(f"Planner failed: {e}")
            # Fallback to single step
            return ExecutionPlan(
                steps=[
                    PlanStep(
                        tool=intent_tool,
                        parameters=intent.entities or {},
                    )
                ],
                description=f"Fallback: Execute {intent_tool}",
            )


# Global singleton
_planner: Optional[Planner] = None


def get_planner() -> Planner:
    """Get or create global planner instance."""
    global _planner
    if _planner is None:
        _planner = Planner()
    return _planner