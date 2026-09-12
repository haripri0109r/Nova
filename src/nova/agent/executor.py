"""Skill execution logic."""
from __future__ import annotations
import asyncio
import inspect
import logging
import time
from typing import Any, Dict, List, Optional
from datetime import datetime

from .models import (
    ExecutionResult, ActionResult, ToolAction, ExecutionPlan, ExecutionContext
)
from .exceptions import SkillNotFoundError
from .task_controller import TaskController, TaskPaused, TaskCancelled

logger = logging.getLogger("nova.agent.executor")


class PlanExecutor:
    """Executes an execution plan with sequential steps, dependency checking, and retry handling."""

    def __init__(self, timeout_policy=None, retry_policy=None, skill_manager=None, event_bus=None):
        self.timeout_policy = timeout_policy
        self.retry_policy = retry_policy
        self._registry = None
        self._skill_manager = skill_manager
        self._event_bus = event_bus

    def _get_registry(self):
        if self._registry is None:
            from .registry import get_skill_registry
            self._registry = get_skill_registry()
        return self._registry

    def _get_timeout(self, skill_name: str) -> float:
        """Get timeout for a skill."""
        return 30.0  # default 30 seconds

    def _extract_parameters(self, action) -> Dict[str, Any]:
        """Extract parameters from various action types."""
        if hasattr(action, 'parameters') and action.parameters:
            return action.parameters
        
        params = {}
        for attr in ['level', 'amount', 'action', 'application', 'target', 'browser', 'url']:
            value = getattr(action, attr, None)
            if value is not None:
                params[attr] = value
        
        if isinstance(action, dict):
            return action.get('parameters', action)
        
        return params

    def _validate_dependencies(self, actions):
        """Validate that all dependencies are valid."""
        for i, action in enumerate(actions):
            depends_on = getattr(action, 'depends_on', [])
            for dep in depends_on:
                if dep < 0:
                    raise ValueError(f"Step {i} has negative dependency index: {dep}")
                if dep >= len(actions):
                    raise ValueError(f"Step {i} depends on step {dep} which doesn't exist (plan has {len(actions)} steps)")
                if dep >= i:
                    raise ValueError(f"Step {i} depends on step {dep} which is not a previous step (forward reference not allowed)")
                if dep == i:
                    raise ValueError(f"Step {i} has self-dependency")

    def _adapt_to_task(self, plan: Any, context: Optional[Any] = None) -> "Task":
        """Convert plan and context into canonical Task domain model without duplicating execution paths."""
        from .models import Task, TaskStep, ExecutionPlan, ExecutionContext, ActionStatus, TaskStatus

        # Extract actions
        actions = getattr(plan, 'steps', None)
        if not actions:
            actions = getattr(plan, 'intents', None)
        if not actions:
            actions = []
        if hasattr(actions, 'actions'):
            actions = actions.actions

        steps: List[TaskStep] = []
        for i, act in enumerate(actions):
            if isinstance(act, TaskStep):
                steps.append(act)
            else:
                if hasattr(act, 'tool'):
                    tool_name = act.tool
                elif hasattr(act, 'intent'):
                    tool_name = act.intent
                elif isinstance(act, dict):
                    tool_name = act.get('tool') or act.get('intent') or "unknown"
                else:
                    tool_name = getattr(act, 'tool', getattr(act, 'intent', 'unknown'))
                
                params = self._extract_parameters(act)
                dep = getattr(act, 'depends_on', [])
                desc = getattr(act, 'description', "")
                steps.append(TaskStep(
                    step_index=i,
                    tool=tool_name,
                    parameters=params,
                    description=desc,
                    depends_on=dep,
                ))

        # Check existing step results from context to restore step statuses if any
        if isinstance(context, ExecutionContext):
            for res in context.step_results:
                s_idx = res.get("step")
                if s_idx is not None:
                    # Could be 1-based or 0-based
                    idx = s_idx - 1 if (0 < s_idx <= len(steps)) else s_idx
                    if 0 <= idx < len(steps):
                        if res.get("success"):
                            steps[idx].status = ActionStatus.SUCCESS
                            steps[idx].result = res.get("result")
                        else:
                            steps[idx].status = ActionStatus.FAILED
                            steps[idx].error = res.get("error")

        session_id = getattr(context, 'session_id', 'default') if context else 'default'
        task_id = getattr(context, 'task_id', None) or getattr(context, 'execution_id', None) or "task_exec"
        max_steps = getattr(context, 'max_steps', None) if context else None
        timeout_sec = getattr(context, 'wall_clock_timeout_seconds', None) if context else None

        return Task(
            id=task_id,
            session_id=session_id,
            steps=steps,
            max_steps=max_steps,
            wall_clock_timeout_seconds=timeout_sec,
            context=context if isinstance(context, ExecutionContext) else None,
            status=TaskStatus.RUNNING,
        )

    async def execute_task_async(
        self,
        task: "Task",
        controller: Optional["TaskController"] = None,
        on_step_update: Optional[Any] = None,
    ) -> "ExecutionResult":
        """
        THE ONLY CANONICAL STEP EXECUTION IMPLEMENTATION IN NOVA.
        Iterates over task.steps, enforces dependencies, handles safe pause/cancel boundaries,
        executes skills, and reports progress via on_step_update.
        """
        from .models import ActionStatus, ExecutionResult, ActionResult, ExecutionContext

        start_time = datetime.utcnow()
        results: List[ActionResult] = []
        failed = False
        steps_summary = []

        if not task.steps:
            return ExecutionResult(
                success=True,
                message="No actions to execute",
                results=[],
                started_at=start_time,
                completed_at=datetime.utcnow()
            )

        # Validate step dependencies before execution
        self._validate_dependencies(task.steps)

        context = task.context

        for i, step in enumerate(task.steps):
            # 1. RESUME CHECK: Skip already completed successful steps
            if step.status == ActionStatus.SUCCESS:
                res_obj = ActionResult(
                    tool=step.tool,
                    success=True,
                    execution_time_ms=step.execution_time_ms,
                    result=step.result,
                )
                results.append(res_obj)
                steps_summary.append({
                    "step": i + 1,
                    "tool": step.tool,
                    "success": True,
                    "result": step.result,
                    "error": None,
                    "execution_time_ms": step.execution_time_ms,
                })
                continue

            # 1b. DEFENSE-IN-DEPTH: Reject automatic execution of INTERRUPTED step
            if step.status == ActionStatus.INTERRUPTED:
                logger.error(
                    f"PlanExecutor encountered INTERRUPTED step {i} ({step.tool}) for task {task.id}. "
                    "Automatic execution is forbidden."
                )
                return ExecutionResult(
                    success=False,
                    message=f"Step {i} ({step.tool}) is in INTERRUPTED state. Outcome is unknown and cannot be executed automatically.",
                    results=results,
                    started_at=start_time,
                    completed_at=datetime.utcnow()
                )

            # 2. SAFE BOUNDARY CHECKS: Cancel and Pause
            if controller is not None:
                if controller.is_cancelled:
                    raise TaskCancelled(task.id)
                if controller.is_paused:
                    raise TaskPaused(task.id)

            # 3. EXECUTION LIMITS: max_steps
            max_steps = task.max_steps
            if max_steps is None and context is not None:
                max_steps = getattr(context, 'max_steps', None)
            if max_steps is not None and i >= max_steps:
                return ExecutionResult(
                    success=False,
                    message=f"Maximum steps ({max_steps}) exceeded",
                    results=results,
                    started_at=start_time,
                    completed_at=datetime.utcnow()
                )

            # 4. EXECUTION LIMITS: wall_clock_timeout_seconds
            timeout_sec = task.wall_clock_timeout_seconds
            if timeout_sec is None and context is not None:
                timeout_sec = getattr(context, 'wall_clock_timeout_seconds', None)
            if timeout_sec is not None:
                elapsed = (datetime.utcnow() - start_time).total_seconds()
                if elapsed > timeout_sec or timeout_sec == 0:
                    return ExecutionResult(
                        success=False,
                        message=f"Wall-clock timeout ({timeout_sec}s) exceeded",
                        results=results,
                        started_at=start_time,
                        completed_at=datetime.utcnow()
                    )

            # 5. DEPENDENCY CHECK: Ensure all prerequisite steps have ActionStatus.SUCCESS
            if step.depends_on:
                dep_failed = False
                for dep_idx in step.depends_on:
                    if dep_idx < 0 or dep_idx >= len(task.steps):
                        dep_failed = True
                        break
                    dep_step = task.steps[dep_idx]
                    if dep_step.status != ActionStatus.SUCCESS:
                        dep_failed = True
                        break
                if dep_failed:
                    step.mark_skipped(f"Dependency step failed or incomplete")
                    if on_step_update is not None:
                        await on_step_update(step, task)
                    return ExecutionResult(
                        success=False,
                        message=f"Step {i} dependency check failed",
                        results=results,
                        started_at=start_time,
                        completed_at=datetime.utcnow()
                    )

            # 6. STEP START LIFECYCLE
            step.mark_running()
            task.current_step_index = i
            if isinstance(context, ExecutionContext):
                context.current_step = i

            if on_step_update is not None:
                try:
                    await on_step_update(step, task)
                except Exception as e:
                    logger.error(f"Persistence error on step start: {e}")
                    step.mark_failed(f"Persistence error: {e}")
                    return ExecutionResult(
                        success=False,
                        message=f"Persistence error: {e}",
                        results=results,
                        started_at=start_time,
                        completed_at=datetime.utcnow()
                    )

            # 7. EXECUTE STEP WITH RETRY SUPPORT
            action_params = step.parameters
            max_retries = getattr(step, 'max_retries', 0)
            retry_count = getattr(step, 'retry_count', 0)
            result = None

            while True:
                result = await self._execute_action_async(step, action_params, context)
                if result.success:
                    break
                if retry_count < max_retries:
                    retry_count += 1
                    step.retry_count = retry_count
                    logger.warning(f"Retrying step {i} (attempt {retry_count}/{max_retries})")
                    await asyncio.sleep(0.05)
                else:
                    break

            # 8. STEP RESULT PROCESSING & PERSISTENCE
            step_summary = {
                "step": i + 1,
                "tool": step.tool,
                "success": result.success,
                "result": result.result,
                "error": result.error,
                "execution_time_ms": result.execution_time_ms,
            }
            steps_summary.append(step_summary)
            results.append(result)

            if isinstance(context, ExecutionContext):
                context.step_results.append(step_summary)

            if result.success:
                step.mark_success(result.result, result.execution_time_ms)
            else:
                step.mark_failed(result.error or "Step execution failed", result.execution_time_ms)
                failed = True

            if on_step_update is not None:
                try:
                    await on_step_update(step, task)
                except Exception as e:
                    logger.error(f"Persistence error on step completion: {e}")
                    return ExecutionResult(
                        success=False,
                        message=f"Persistence error: {e}",
                        results=results,
                        started_at=start_time,
                        completed_at=datetime.utcnow()
                    )

            if failed:
                break

        # Build final ExecutionResult
        success = not failed
        completed_at = datetime.utcnow()

        error_msg = "Execution failed"
        if failed and steps_summary:
            error_msg = steps_summary[-1].get("error") or "Execution failed"

        if success and results:
            first_result = results[0].result
            if isinstance(first_result, dict) and first_result.get("detail"):
                detail_val = first_result["detail"]
                success_msg = detail_val if isinstance(detail_val, str) else str(detail_val)
            else:
                success_msg = "Execution completed"
        else:
            success_msg = "Execution completed"

        return ExecutionResult(
            success=success,
            message=success_msg if not failed else error_msg,
            results=results,
            started_at=start_time,
            completed_at=completed_at
        )

    async def execute_async(self, plan, context=None, controller=None) -> "ExecutionResult":
        """
        Backward-compatibility adapter for plan execution.
        Adapts the plan and context to a Task and delegates to execute_task_async().
        Contains NO independent execution loop.
        """
        task = self._adapt_to_task(plan, context)
        return await self.execute_task_async(task, controller=controller)

    async def execute_async_with_context(self, plan, context=None, controller=None) -> "ExecutionResult":
        """
        Backward-compatibility adapter for plan execution with context.
        Delegates directly to execute_async().
        """
        return await self.execute_async(plan, context, controller=controller)


    async def _execute_action_async(self, action, action_params: Dict[str, Any], context) -> 'ActionResult':
        """Execute a single action asynchronously."""
        from .models import ActionResult
        from .registry import get_skill_registry

        if hasattr(action, 'tool'):
            action_tool = action.tool
        elif hasattr(action, 'intent'):
            action_tool = action.intent
        elif isinstance(action, dict):
            action_tool = action.get('tool') or action.get('intent')
        else:
            action_tool = getattr(action, 'tool', getattr(action, 'intent', 'unknown'))

        # Build intent_data dict compatible with BaseSkill.execute()
        intent_data = {
            "intent": action_tool,
            "parameters": action_params,
        }
        # Unpack parameters to top level so skills expecting top-level keys receive them
        if isinstance(action_params, dict):
            intent_data.update(action_params)
        if getattr(action, 'action', None):
            intent_data["action"] = getattr(action, 'action')

        if isinstance(context, ExecutionContext):
            intent_data["_context"] = context

        # If skill_manager is injected (for tests or routing), execute through it
        if self._skill_manager is not None:
            exec_async = getattr(self._skill_manager, "execute_intent_async", None)
            if callable(exec_async) and inspect.iscoroutinefunction(exec_async):
                result = await exec_async(intent_data)
            else:
                result = self._skill_manager.execute_intent(intent_data)
                if inspect.isawaitable(result):
                    result = await result

            if isinstance(result, dict) and result.get("status") == "ok":
                skill_result = result.get("result")
                if skill_result is None:
                    detail = result.get("detail")
                    skill_result = {"detail": detail} if detail is not None else {}
                return ActionResult(
                    tool=action_tool,
                    success=True,
                    execution_time_ms=10,
                    result=skill_result
                )
            else:
                err_msg = result.get("message", "Unknown error") if isinstance(result, dict) else str(result)
                return ActionResult(
                    tool=action_tool,
                    success=False,
                    execution_time_ms=10,
                    error=err_msg
                )

        # Fallback to registry
        registry = self._get_registry()
        skill = registry.get(action_tool, intent_data)
        if not skill:
            return ActionResult(
                tool=action_tool,
                success=False,
                execution_time_ms=0,
                error=f"Skill '{action_tool}' not found"
            )

        start_time = time.time()
        timeout = self._get_timeout(action_tool)

        # Retry logic with backoff
        for attempt in range(3):
            try:
                result = await self._execute_skill_async(skill, intent_data, timeout)

                if isinstance(result, dict) and result.get("status") == "error":
                    return ActionResult(
                        tool=action_tool,
                        success=False,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        error=result.get("message", "Skill returned error")
                    )

                if isinstance(result, dict):
                    skill_result = result.get("result")
                    if skill_result is None:
                        detail = result.get("detail")
                        skill_result = {"detail": detail} if detail is not None else {}
                else:
                    skill_result = {}

                execution_time = (time.time() - start_time) * 1000
                return ActionResult(
                    tool=action_tool,
                    success=True,
                    execution_time_ms=int(execution_time),
                    result=skill_result
                )

            except asyncio.TimeoutError:
                logger.warning(f"Skill {action_tool} timed out (attempt {attempt + 1})")
                if attempt == 2:
                    return ActionResult(
                        tool=action_tool,
                        success=False,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        error=f"Timeout after {timeout}s"
                    )
            except Exception as e:
                logger.error(f"Error executing skill {action_tool}: {e}")
                if attempt == 2:
                    return ActionResult(
                        tool=action_tool,
                        success=False,
                        execution_time_ms=int((time.time() - start_time) * 1000),
                        error=str(e)
                    )
                await asyncio.sleep(2 ** attempt)

        return ActionResult(
            tool=action_tool,
            success=False,
            execution_time_ms=int((time.time() - start_time) * 1000),
            error="Max retries exceeded"
        )

    async def _execute_skill_async(self, skill, intent_data, timeout) -> Any:
        """Execute a skill asynchronously without unawaited coroutines."""
        if inspect.iscoroutinefunction(skill.execute):
            coro = skill.execute(intent_data)
            return await asyncio.wait_for(coro, timeout=timeout)
        else:
            loop = asyncio.get_running_loop()
            res = await loop.run_in_executor(None, lambda: skill.execute(intent_data))
            if inspect.isawaitable(res):
                res = await res
            return res

    # Backward compatibility: synchronous wrapper for legacy tests
    def execute(self, plan, context="") -> Dict[str, Any]:
        """
        Synchronous wrapper for backward compatibility with legacy synchronous unit tests.
        Raises RuntimeError if an event loop is already running.
        """
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            raise RuntimeError(
                "Cannot call synchronous PlanExecutor.execute() while an event loop is running. "
                "Use 'await executor.execute_async(plan, context)' instead."
            )

        result = asyncio.run(self.execute_async(plan, context))

        steps = []
        failed_at_step = None
        for i, r in enumerate(result.results):
            steps.append({
                "step": i + 1,
                "tool": r.tool,
                "success": r.success,
                "result": r.result,
                "error": r.error,
                "execution_time_ms": r.execution_time_ms
            })
            if not r.success and failed_at_step is None:
                failed_at_step = i + 1

        return {
            "status": "completed" if result.success else "error",
            "message": result.message,
            "results": [
                {"tool": r.tool, "success": r.success, "result": r.result, "error": r.error, "execution_time_ms": r.execution_time_ms}
                for r in result.results
            ],
            "steps": steps,
            "failed_at_step": failed_at_step,
            "total_time_ms": int((result.completed_at - result.started_at).total_seconds() * 1000) if result.completed_at and result.started_at else 0
        }


__all__ = ["PlanExecutor"]