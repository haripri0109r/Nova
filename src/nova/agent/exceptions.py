"""Custom exceptions for the Agent Orchestrator."""
from typing import Optional, Dict, Any


class AgentError(Exception):
    """Base exception for Agent Orchestrator errors."""
    def __init__(self, message: str, code: str = "AGENT_ERROR", details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def __str__(self):
        return f"[{self.code}] {self.message}"


class SkillNotFoundError(AgentError):
    def __init__(self, skill_name: str):
        super().__init__(f"Skill '{skill_name}' not found", code="SKILL_NOT_FOUND",
                         details={"skill_name": skill_name})


class SkillExecutionError(AgentError):
    def __init__(self, skill_name: str, message: str, details: dict | None = None):
        super().__init__(f"Skill '{skill_name}' execution failed: {message}",
                         code="SKILL_EXECUTION_ERROR",
                         details={**({"skill_name": skill_name}), **(details or {})})


class SkillTimeoutError(AgentError):
    def __init__(self, skill_name: str, timeout: int):
        super().__init__(f"Skill '{skill_name}' timed out after {timeout}s",
                         code="SKILL_TIMEOUT", details={"skill_name": skill_name, "timeout": timeout})


class ValidationError(AgentError):
    def __init__(self, message: str, field: str | None = None):
        super().__init__(message, code="VALIDATION_ERROR",
                         details={"field": field} if field else {})


class RegistryError(AgentError):
    def __init__(self, message: str, skill_name: str | None = None):
        super().__init__(message, code="REGISTRY_ERROR",
                         details={"skill_name": skill_name} if skill_name else {})


class ConfigurationError(AgentError):
    def __init__(self, message: str, config_key: str | None = None):
        super().__init__(message, code="CONFIGURATION_ERROR",
                         details={"config_key": config_key} if config_key else {})


class ExecutionError(AgentError):
    def __init__(self, message: str, execution_id: str | None = None):
        super().__init__(message, code="EXECUTION_ERROR",
                         details={"execution_id": execution_id} if execution_id else {})


class InvalidStateTransitionError(AgentError, ValueError):
    """Raised when an illegal task state transition is attempted."""
    def __init__(self, from_state: str, to_state: str, task_id: Optional[str] = None):
        msg = f"Invalid state transition from '{from_state}' to '{to_state}'"
        if task_id:
            msg += f" for task '{task_id}'"
        super().__init__(
            msg,
            code="INVALID_STATE_TRANSITION",
            details={"from_state": from_state, "to_state": to_state, "task_id": task_id}
        )


class TaskInterruptedStepError(AgentError):
    """Raised when resuming a task that contains an unresolved INTERRUPTED step."""
    def __init__(self, task_id: str, step_index: int, tool: str = "", message: Optional[str] = None):
        msg = message or f"Cannot resume task '{task_id}': Step {step_index + 1} ({tool}) was interrupted. Outcome is unknown."
        super().__init__(
            msg,
            code="TASK_INTERRUPTED_STEP",
            details={"task_id": task_id, "step_index": step_index, "tool": tool}
        )
        self.task_id = task_id
        self.step_index = step_index
        self.tool = tool


class StepRetryLimitExceededError(AgentError):
    """Raised when RETRY_STEP is requested but the step has exhausted its retry budget."""
    def __init__(self, task_id: str, step_index: int, retry_count: int, max_retries: int):
        msg = (
            f"Step {step_index} in task '{task_id}' has exceeded its retry limit "
            f"({retry_count}/{max_retries}). Use SKIP_STEP to bypass."
        )
        super().__init__(msg, code="STEP_RETRY_LIMIT_EXCEEDED",
                         details={"task_id": task_id, "step_index": step_index,
                                  "retry_count": retry_count, "max_retries": max_retries})
        self.task_id = task_id
        self.step_index = step_index
        self.retry_count = retry_count
        self.max_retries = max_retries


class StepNotInterruptedError(AgentError):
    """Raised when RETRY_STEP or SKIP_STEP targets a step that is not INTERRUPTED."""
    def __init__(self, task_id: str, step_index: int, actual_status: str):
        msg = (
            f"Step {step_index} in task '{task_id}' is not INTERRUPTED "
            f"(current status: {actual_status}). RETRY_STEP and SKIP_STEP only apply to INTERRUPTED steps."
        )
        super().__init__(msg, code="STEP_NOT_INTERRUPTED",
                         details={"task_id": task_id, "step_index": step_index,
                                  "actual_status": actual_status})
        self.task_id = task_id
        self.step_index = step_index
        self.actual_status = actual_status


class HighRiskConfirmationRequiredError(AgentError):
    """Raised when a high-risk RETRY_STEP requires explicit user confirmation before execution."""
    def __init__(self, task_id: str, step_index: int, tool: str, confirmation_token: str, expires_at: str):
        msg = (
            f"Step {step_index} ({tool}) in task '{task_id}' is classified as HIGH RISK. "
            f"To confirm retry, respond with token: {confirmation_token} (expires: {expires_at})."
        )
        super().__init__(msg, code="HIGH_RISK_CONFIRMATION_REQUIRED",
                         details={"task_id": task_id, "step_index": step_index, "tool": tool,
                                  "confirmation_token": confirmation_token, "expires_at": expires_at})
        self.task_id = task_id
        self.step_index = step_index
        self.tool = tool
        self.confirmation_token = confirmation_token
        self.expires_at = expires_at


class ConfirmationExpiredError(AgentError):
    """Raised when a confirmation token for a high-risk retry has expired."""
    def __init__(self, task_id: str, step_index: int, token: str):
        msg = f"Confirmation token '{token}' for step {step_index} of task '{task_id}' has expired."
        super().__init__(msg, code="CONFIRMATION_EXPIRED",
                         details={"task_id": task_id, "step_index": step_index, "token": token})
        self.task_id = task_id
        self.step_index = step_index
        self.token = token


class ConfirmationMismatchError(AgentError):
    """Raised when a confirmation token does not match the pending confirmation."""
    def __init__(self, task_id: str, step_index: int):
        msg = f"Confirmation token mismatch for step {step_index} of task '{task_id}'."
        super().__init__(msg, code="CONFIRMATION_MISMATCH",
                         details={"task_id": task_id, "step_index": step_index})
        self.task_id = task_id
        self.step_index = step_index