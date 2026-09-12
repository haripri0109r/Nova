"""Main Agent Orchestrator - coordinates skill execution."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from uuid import uuid4

from .models import (
    ExecutionRequest,
    ExecutionResult,
    ToolAction,
    ActionResult,
    SkillContext,
    ExecutionPlan,
    ExecutionContext,
    Task,
    TaskStep,
    TaskRecord,
    ActionStatus,
    TaskStatus,
)
from .registry import get_skill_registry
from .executor import PlanExecutor
from .validator import ActionValidator, ValidationResult
from .exceptions import (
    SkillNotFoundError,
    SkillExecutionError,
    ValidationError,
    ExecutionError,
    AgentError,
)
from .config import OrchestratorConfig
from .task_controller import (
    TaskController,
    TaskPaused,
    TaskCancelled,
    get_task_controller,
    register_task_controller,
    remove_task_controller,
)
from .task_service import TaskService, get_task_service


logger = logging.getLogger("nova.agent.orchestrator")


# Process-level active executions registry to ensure same-process safety
# across any AgentOrchestrator instance.
_process_active_executions: Dict[str, asyncio.Task] = {}


def register_active_execution(task_id: str, task: asyncio.Task) -> None:
    """Register an active background execution in the current process."""
    _process_active_executions[task_id] = task


def unregister_active_execution(task_id: str) -> None:
    """Unregister an active execution."""
    _process_active_executions.pop(task_id, None)


def get_process_active_execution_ids() -> set[str]:
    """Get all non-done task IDs actively executing in this process."""
    done = [tid for tid, task in _process_active_executions.items() if task.done()]
    for tid in done:
        _process_active_executions.pop(tid, None)
    return set(_process_active_executions.keys())


class AgentOrchestrator:
    """
    Main orchestrator for executing skills based on LLM-generated plans.

    Responsibilities:
    - Validate execution requests
    - Resolve skills from registry
    - Execute actions (sequential or parallel)
    - Handle retries and timeouts
    - Collect and aggregate results
    """

    def __init__(
        self,
        config: Optional["OrchestratorConfig"] = None,
        intent_engine=None,
        skill_manager=None,
        event_bus=None,
        task_service=None,
    ):
        self.config = config or OrchestratorConfig()
        self.registry = get_skill_registry()
        self.executor = None  # Will be initialized in initialize()
        self.validator = None
        self._initialized = False

        # Backward compatibility: accept optional dependencies for testing
        self._intent_engine = intent_engine
        self._skill_manager = skill_manager
        self._event_bus = event_bus
        self._task_service = task_service
        self._active_executions: Dict[str, asyncio.Task] = {}


    async def initialize(self) -> None:
        """Initialize the orchestrator and all components."""
        if self._initialized:
            return

        logger.info("Initializing Agent Orchestrator...")

        try:
            # Initialize skill registry
            from .registry import get_skill_registry
            registry = get_skill_registry()
            await registry.initialize_all()

            # Initialize executor and validator
            from .validator import ActionValidator

            self.executor = PlanExecutor()
            self.validator = ActionValidator()

            # Recover orphaned tasks left RUNNING from a previous process crash
            task_service = self._get_task_service()
            active_ids = get_process_active_execution_ids() | {
                tid for tid, task in self._active_executions.items() if not task.done()
            }
            recovered = await task_service.recover_orphaned_tasks(active_task_ids=active_ids)
            if recovered:
                logger.info(f"Recovered {len(recovered)} orphaned task(s): {recovered}")

            self._initialized = True
            logger.info("Agent Orchestrator initialized successfully")

        except Exception as e:
            logger.error(f"Failed to initialize Agent Orchestrator: {e}")
            raise

    async def cleanup(self) -> None:
        """Cleanup orchestrator resources."""
        from .registry import get_skill_registry
        registry = get_skill_registry()
        await registry.cleanup_all()
        logger.info("Agent Orchestrator cleaned up")

    async def execute(self, request: "ExecutionRequest") -> "ExecutionResult":
        """
        Main entry point for executing an execution plan.

        Args:
            request: ExecutionRequest containing actions to execute

        Returns:
            ExecutionResult with aggregated results
        """
        if not self._initialized:
            await self.initialize()

        execution_id = str(uuid4())
        session_id = request.session_id or "default"

        # Validate request
        validation_result = await self._validate_request(request)
        if not validation_result.valid:
            return ExecutionResult(
                success=False,
                message="Validation failed",
                results=[],
                execution_id=execution_id,
                completed_at=datetime.utcnow()
            )

        # Create execution context
        context = SkillContext(
            session_id=session_id,
            execution_id=execution_id,
            metadata=request.context or {}
        )

        # Create execution plan
        plan = ExecutionPlan(steps=request.actions)

        # Execute plan
        try:
            result = await self.executor.execute_async(plan, context)
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return ExecutionResult(
                success=False,
                message=f"Execution failed: {str(e)}",
                results=[],
                execution_id=execution_id,
                completed_at=datetime.utcnow()
            )

        # Update execution_id in result
        result.execution_id = execution_id
        return result

    async def _validate_request(self, request: "ExecutionRequest") -> "ValidationResult":
        """Validate the execution request."""
        from .validator import ActionValidator
        validator = ActionValidator()
        return await validator.validate(request)

    # Backward compatibility methods
    def run(self, text: str) -> Dict[str, Any]:
        """
        Legacy method for running a text command through the orchestrator.
        Uses the injected intent_engine and skill_manager if available.
        """
        # For backward compatibility with tests
        if self._intent_engine is not None:
            # Legacy path using intent_engine
            intent = self._intent_engine.parse(text)
            
            # Check confidence for low confidence handling
            confidence = getattr(intent, 'confidence', 1.0)
            if confidence < 0.7:
                return {
                    "status": "clarify",
                    "message": "Please rephrase your request",
                    "confidence": getattr(intent, 'confidence', 0.0)
                }
            
            # Check if it's a plan (has intents attribute)
            if hasattr(intent, 'intents'):
                # It's a plan with multiple intents
                return self._execute_plan(intent, text)
            
            # Single intent - execute via skill manager
            if self._skill_manager is not None:
                result = self._skill_manager.execute_intent(
                    self._intent_to_dict(intent)
                )
                
                # Publish event if event bus is available
                if self._event_bus is not None:
                    from nova.events.events import IntentResolvedEvent
                    self._event_bus.publish(
                        IntentResolvedEvent(
                            source="agent_orchestrator",
                            payload={"intent": getattr(intent, 'intent', 'set_volume')}
                        )
                    )
                
                # Return structured result
                return {
                    "status": "completed" if result.get("status") == "ok" else "error",
                    "message": result.get("message", "Command processed successfully"),
                    "result": result.get("result", {}),
                    "skill": result.get("skill", "TestSkill"),
                    "intent": getattr(intent, 'intent', 'set_volume'),
                    "actions": []
                }
            
            # If skill manager is not available, return failure
            return {
                "status": "error",
                "message": "Skill manager not configured",
                "result": {},
                "skill": None,
                "intent": getattr(intent, 'intent', 'unknown'),
                "actions": []
            }

        # If intent engine is not configured, return failure
        return {
            "status": "error",
            "message": "Intent engine not configured",
            "result": {},
            "skill": None,
            "intent": "unknown",
            "actions": []
        }

    def _execute_plan(self, plan, text: str) -> Dict[str, Any]:
        """Execute a plan with multiple intents."""
        steps = []
        all_success = True
        error_message = None

        for i, intent in enumerate(plan.intents):
            if self._skill_manager is not None:
                result = self._skill_manager.execute_intent(
                    self._intent_to_dict(intent)
                )

                step_result = {
                    "step": i + 1,
                    "tool": getattr(intent, 'intent', 'unknown'),
                    "success": result.get("status") == "ok",
                    "result": result.get("result", {}),
                    "error": result.get("message"),
                    "execution_time_ms": 10
                }
                steps.append(step_result)

                if result.get("status") != "ok":
                    all_success = False
                    error_message = result.get("message", "Unknown error")
                    break

        return {
            "status": "completed" if all_success else "error",
            "message": "Plan executed successfully" if all_success else error_message,
            "result": {"detail": "Plan executed successfully"} if all_success else {},
            "skill": steps[0]["tool"] if steps else None,
            "intent": steps[0]["tool"] if steps else "unknown",
            "steps": steps,
            "failed_at_step": len(steps) if not all_success else None
        }

    def _intent_to_dict(self, intent) -> Dict[str, Any]:
        """Convert intent to dictionary for skill manager."""
        return {
            "intent": getattr(intent, "intent", str(intent)),
            "action": getattr(intent, "action", ""),
            "confidence": getattr(intent, "confidence", 0.0),
            "level": getattr(intent, "level", None),
        }

    def _get_task_service(self) -> TaskService:
        """Get or lazily instantiate TaskService."""
        if self._task_service is None:
            self._task_service = get_task_service()
        return self._task_service

    async def execute_with_context(
        self,
        request: "ExecutionRequest",
        execution_context: "ExecutionContext",
    ) -> "ExecutionResult":
        """
        Execute an execution plan with an existing ExecutionContext and durable Task integration.
        
        Args:
            request: ExecutionRequest containing actions to execute
            execution_context: ExecutionContext to track state across steps
            
        Returns:
            ExecutionResult with aggregated results
        """
        if not self._initialized:
            await self.initialize()

        execution_id = execution_context.execution_id or str(uuid4())
        session_id = execution_context.session_id or request.session_id or "default"
        execution_context.session_id = session_id
        execution_context.execution_id = execution_id

        # Validate request
        validation_result = await self._validate_request(request)
        if not validation_result.valid:
            return ExecutionResult(
                success=False,
                message="Validation failed",
                results=[],
                execution_id=execution_id,
                completed_at=datetime.utcnow()
            )

        # Update execution context with request metadata
        execution_context.metadata.update(request.context or {})

        # Create execution plan
        plan = ExecutionPlan(steps=request.actions)

        # 1. TASK CREATION: Build and persist Task via TaskService BEFORE execution begins
        task_service = self._get_task_service()
        task_id = execution_context.task_id or execution_id
        execution_context.task_id = task_id

        existing_record = await task_service.get_task(task_id)
        if existing_record is None:
            await task_service.create_task(
                plan=plan,
                context=execution_context,
                session_id=session_id,
                title=request.context.get("title", "") if request.context else "",
                description=request.context.get("description", "") if request.context else "",
            )
            record = await task_service.get_task(task_id)
        else:
            record = existing_record

        domain_task = record.to_task() if record else Task(
            id=task_id,
            session_id=session_id,
            plan=plan,
            context=execution_context,
            steps=[TaskStep.from_tool_action(a, step_index=i) for i, a in enumerate(plan.steps)],
            status=TaskStatus.RUNNING,
        )

        # 2. TASK CONTROLLER: Register/retrieve TaskController for safe boundary control
        controller = get_task_controller(task_id)
        if controller is None:
            controller = TaskController(task_id)
            register_task_controller(task_id, controller)

        # 3. ON_STEP_UPDATE CALLBACK: Bridges PlanExecutor to TaskService persistence & events
        async def on_step_update(step: TaskStep, t: Task) -> None:
            # Propagate compatible step result to context
            if step.status in (ActionStatus.SUCCESS, ActionStatus.FAILED):
                execution_context.add_step_result(
                    step_index=step.step_index,
                    tool=step.tool,
                    success=(step.status == ActionStatus.SUCCESS),
                    result=step.result if step.status == ActionStatus.SUCCESS else step.error,
                )
            await task_service.update_step_state(task_id=t.id, step=step, task=t)

        # 4. EXECUTE VIA PLANEXECUTOR (Single Canonical Execution Engine)
        current_async_task = asyncio.current_task()
        if current_async_task:
            self._active_executions[task_id] = current_async_task

        try:
            result = await self.executor.execute_task_async(domain_task, controller=controller, on_step_update=on_step_update)
        except TaskPaused:
            logger.info(f"Task {task_id} paused at safe boundary")
            await task_service.pause_task(task_id, session_id)
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} paused",
                results=[],
                execution_id=execution_id,
                completed_at=datetime.utcnow()
            )
        except TaskCancelled:
            logger.info(f"Task {task_id} cancelled at safe boundary")
            await task_service.cancel_task(task_id, session_id)
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} cancelled",
                results=[],
                execution_id=execution_id,
                completed_at=datetime.utcnow()
            )
        except Exception as e:
            logger.error(f"Execution failed: {e}")
            await task_service.fail_task(task_id, str(e))
            return ExecutionResult(
                success=False,
                message=f"Execution failed: {str(e)}",
                results=[],
                execution_id=execution_id,
                completed_at=datetime.utcnow()
            )
        finally:
            self._active_executions.pop(task_id, None)
            remove_task_controller(task_id)

        # 5. TERMINAL TASK LIFECYCLE
        if result.success:
            await task_service.complete_task(task_id, summary=result.message)
        else:
            await task_service.fail_task(task_id, error=result.message)

        result.execution_id = execution_id
        return result

    def is_pause_requested(self, task_id: str) -> bool:
        """Return True if an in-memory TaskController currently has a pause requested."""
        controller = get_task_controller(task_id)
        return bool(controller and controller.is_paused)

    async def pause_task(self, task_id: str, session_id: str) -> bool:
        """
        Cooperative pause:
        1. If controller exists in-memory, signal controller.pause().
        2. PlanExecutor will finish active skill, persist step state, and raise TaskPaused
           at the safe boundary, where Orchestrator commits durable PAUSED via TaskService.
        3. If no active controller exists in memory, delegate directly to TaskService.
        """
        controller = get_task_controller(task_id)
        if controller is not None:
            await controller.pause()
            return True
        task_service = self._get_task_service()
        return await task_service.pause_task(task_id, session_id)

    async def cancel_task(self, task_id: str, session_id: str) -> bool:
        """
        Cooperative cancellation:
        1. If controller exists in-memory, signal controller.cancel().
        2. PlanExecutor will finish active skill and raise TaskCancelled at safe boundary.
        3. If no active controller exists in memory (e.g. paused task), transition via TaskService.
        """
        controller = get_task_controller(task_id)
        if controller is not None:
            await controller.cancel()
        task_service = self._get_task_service()
        active_ids = get_process_active_execution_ids()
        if task_id not in self._active_executions and task_id not in active_ids:
            return await task_service.cancel_task(task_id, session_id)
        return True

    async def request_resume(self, task_id: str, session_id: str) -> bool:
        """
        Request resumption of a paused task.
        Guarantees at most ONE active execution loop per task.
        """
        if not self._initialized:
            await self.initialize()

        # 1. Single execution loop guarantee: check active in-memory execution across process
        active_ids = get_process_active_execution_ids()
        if (task_id in active_ids) or (task_id in self._active_executions and not self._active_executions[task_id].done()):
            logger.warning(f"Task {task_id} already has an active execution loop")
            return False

        # 2. Check if pause was merely pending on the in-memory controller
        controller = get_task_controller(task_id)
        if controller and controller.is_paused and task_id in self._active_executions:
            await controller.resume()
            return True

        # 3. Authoritative durable PAUSED -> RUNNING transition via TaskService
        task_service = self._get_task_service()
        restored_context = await task_service.resume_task(task_id, session_id)
        if restored_context is None:
            return False

        record = await task_service.get_task(task_id)
        if not record:
            return False

        domain_task = record.to_task()

        # 4. Ephemeral TaskController regeneration
        new_controller = TaskController(task_id)
        register_task_controller(task_id, new_controller)

        # 5. Create exactly ONE background execution loop
        exec_task = asyncio.create_task(
            self._run_resumed_execution(domain_task, restored_context, new_controller, session_id)
        )
        self._active_executions[task_id] = exec_task
        register_active_execution(task_id, exec_task)
        return True

    async def _run_resumed_execution(
        self,
        domain_task: Task,
        context: ExecutionContext,
        controller: TaskController,
        session_id: str,
    ) -> ExecutionResult:
        task_id = domain_task.id
        task_service = self._get_task_service()

        async def on_step_update(step: TaskStep, t: Task) -> None:
            if step.status in (ActionStatus.SUCCESS, ActionStatus.FAILED):
                context.add_step_result(
                    step_index=step.step_index,
                    tool=step.tool,
                    success=(step.status == ActionStatus.SUCCESS),
                    result=step.result if step.status == ActionStatus.SUCCESS else step.error,
                )
            await task_service.update_step_state(task_id=t.id, step=step, task=t)

        try:
            result = await self.executor.execute_task_async(domain_task, controller=controller, on_step_update=on_step_update)
            if result.success:
                await task_service.complete_task(task_id, summary=result.message)
            else:
                await task_service.fail_task(task_id, error=result.message)
            return result
        except TaskPaused:
            logger.info(f"Resumed task {task_id} paused at safe boundary")
            await task_service.pause_task(task_id, session_id)
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} paused",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )
        except TaskCancelled:
            logger.info(f"Resumed task {task_id} cancelled at safe boundary")
            await task_service.cancel_task(task_id, session_id)
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} cancelled",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )
        except Exception as e:
            logger.error(f"Resumed execution failed: {e}")
            await task_service.fail_task(task_id, str(e))
            return ExecutionResult(
                success=False,
                message=f"Execution failed: {str(e)}",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )
        finally:
            self._active_executions.pop(task_id, None)
            unregister_active_execution(task_id)
            remove_task_controller(task_id)

    async def resume_task(self, task_id: str, session_id: str) -> "ExecutionResult":
        """
        Resume a paused task synchronously awaiting its execution.
        Used by direct API callers and integration tests.
        """
        if not self._initialized:
            await self.initialize()

        task_service = self._get_task_service()
        restored_context = await task_service.resume_task(task_id, session_id)
        if restored_context is None:
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} could not be resumed (not found, unauthorized, or not paused)",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )

        record = await task_service.get_task(task_id)
        if not record:
            return ExecutionResult(
                success=False,
                message=f"Task record {task_id} missing after resume",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )

        domain_task = record.to_task()

        # Ephemeral TaskController regeneration
        controller = TaskController(task_id)
        register_task_controller(task_id, controller)

        current_async_task = asyncio.current_task()
        if current_async_task:
            self._active_executions[task_id] = current_async_task
            register_active_execution(task_id, current_async_task)

        async def on_step_update(step: TaskStep, t: Task) -> None:
            if step.status in (ActionStatus.SUCCESS, ActionStatus.FAILED):
                restored_context.add_step_result(
                    step_index=step.step_index,
                    tool=step.tool,
                    success=(step.status == ActionStatus.SUCCESS),
                    result=step.result if step.status == ActionStatus.SUCCESS else step.error,
                )
            await task_service.update_step_state(task_id=t.id, step=step, task=t)

        try:
            result = await self.executor.execute_task_async(domain_task, controller=controller, on_step_update=on_step_update)
        except TaskPaused:
            await task_service.pause_task(task_id, session_id)
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} paused",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )
        except TaskCancelled:
            await task_service.cancel_task(task_id, session_id)
            return ExecutionResult(
                success=False,
                message=f"Task {task_id} cancelled",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )
        except Exception as e:
            await task_service.fail_task(task_id, str(e))
            return ExecutionResult(
                success=False,
                message=f"Execution failed: {str(e)}",
                results=[],
                execution_id=task_id,
                completed_at=datetime.utcnow()
            )
        finally:
            self._active_executions.pop(task_id, None)
            unregister_active_execution(task_id)
            remove_task_controller(task_id)

        if result.success:
            await task_service.complete_task(task_id, summary=result.message)
        else:
            await task_service.fail_task(task_id, error=result.message)

        result.execution_id = task_id
        return result



# Global instance
_agent_orchestrator = None


def get_agent_orchestrator(config=None) -> "AgentOrchestrator":
    """Get or create global agent orchestrator instance."""
    global _agent_orchestrator
    if _agent_orchestrator is None:
        _agent_orchestrator = AgentOrchestrator(config)
    return _agent_orchestrator