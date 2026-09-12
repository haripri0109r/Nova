"""Abstract interfaces for skills and registries."""
from __future__ import annotations

import abc
from typing import Any, Dict, List, Optional

from .models import (
    SkillContext,
    SkillDefinition,
    ActionResult,
    ToolAction,
    ExecutionPlan,
    ValidationResult,
)
from .exceptions import ValidationError


class Skill(abc.ABC):
    """Base interface every skill must implement."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        """Unique skill name used for registration."""

    @property
    @abc.abstractmethod
    def description(self) -> str:
        """Human‑readable description of the skill's purpose."""

    @abc.abstractmethod
    async def initialize(self) -> None:
        """One‑time initialization (e.g., load models, open connections)."""

    @abc.abstractmethod
    async def cleanup(self) -> None:
        """Release resources, close connections."""

    @abc.abstractmethod
    async def validate(self, parameters: Dict[str, Any]) -> None:
        """
        Validate parameters before execution.
        Raise ValidationError on failure.
        """

    @abc.abstractmethod
    async def execute(self, parameters: Dict[str, Any], context: "SkillContext") -> Any:
        """Execute the skill and return a result payload."""

    def _parameter_schema(self) -> Dict[str, Any]:
        """Return a JSON Schema for parameters. Override if needed."""
        return {}


class SkillRegistry(abc.ABC):
    """Registry abstraction for skill lookup and registration."""

    @abc.abstractmethod
    def register(self, skill: Skill) -> None:
        """Register a skill instance."""

    @abc.abstractmethod
    def unregister(self, name: str) -> None:
        """Unregister a skill by name."""

    @abc.abstractmethod
    def resolve(self, name: str) -> Skill:
        """
        Retrieve a skill by name.

        Raises:
            SkillNotFoundError: if no skill with the given name is registered.
        """

    @abc.abstractmethod
    def exists(self, name: str) -> bool:
        """Return True if a skill with the given name is registered."""

    @abc.abstractmethod
    def list_skills(self) -> List["SkillDefinition"]:
        """Return definitions of all registered skills."""

    @abc.abstractmethod
    async def initialize_all(self) -> None:
        """Initialize all registered skills."""

    @abc.abstractmethod
    async def cleanup_all(self) -> None:
        """Cleanup all registered skills."""


class ActionValidator(abc.ABC):
    """Contract for request / action validation."""

    @abc.abstractmethod
    async def validate(self, request: "ExecutionRequest") -> "ValidationResult":
        """
        Validate an entire ExecutionRequest.

        Returns:
            ValidationResult indicating validity and any errors.
        """

    @abc.abstractmethod
    async def validate_action(self, action: "ToolAction") -> List[str]:
        """
        Validate a single ToolAction.

        Returns:
            List of error strings (empty = valid).
        """

    @abc.abstractmethod
    async def validate_permissions(
        self, action: "ToolAction", permissions: List[str]
    ) -> List[str]:
        """
        Check permission requirements for a single action.

        Returns:
            List of missing permissions (empty = ok).
        """


class PlanExecutor(abc.ABC):
    """Contract for the execution engine."""

    @abc.abstractmethod
    async def execute(self, plan: "ExecutionPlan", context: "SkillContext") -> "ExecutionResult":
        """
        Execute a full plan and return an aggregated ExecutionResult.

        Must handle retries, timeouts, parallelism, etc.
        """

    @abc.abstractmethod
    async def cancel(self, execution_id: str) -> bool:
        """
        Cancel an in‑flight execution (best‑effort).

        Returns:
            True if the execution was cancelled, False if no such execution was found.
        """


class AgentOrchestratorInterface(abc.ABC):
    """Public façade exposed to the rest of Nova."""

    @abc.abstractmethod
    async def initialize(self) -> None:
        """Initialise all internal components (registry, executor, validator…)."""

    @abc.abstractmethod
    async def cleanup(self) -> None:
        """Release all resources (skills, connections, etc.)."""

    @abc.abstractmethod
    async def execute(self, request: "ExecutionRequest") -> "ExecutionResult":
        """
        Main entry point – translate an ExecutionRequest into an ExecutionResult.

        Orchestrates validation → resolution → execution → aggregation.
        """