"""
Planning abstraction and placeholder implementation.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .models import ExecutionPlan, IntentResult, RecognizedInput, PlanStep
from .types import PlannerConfig
from .exceptions import PlanningError


class BasePlanner(ABC):
    """Abstract planner."""

    def __init__(self, config: Optional[PlannerConfig] = None):
        self.config = config or PlannerConfig()
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        ...

    @abstractmethod
    async def plan(self, intent: IntentResult, inp: RecognizedInput) -> 'ExecutionPlan':
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class PlaceholderPlanner(BasePlanner):
    """Very simple rule‑based planner for offline / testing."""

    def __init__(self, config: Optional[PlannerConfig] = None):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def plan(self, intent: IntentResult, inp: RecognizedInput) -> 'ExecutionPlan':
        from .models import ExecutionPlan, PlanStep
        steps = []
        if intent.category.value == "open_application":
            steps.append(PlanStep(tool="open_application", parameters={"app": inp.text}))
        elif intent.category.value == "close_application":
            steps.append(PlanStep(tool="close_application", parameters={"app": inp.text}))
        else:
            steps.append(PlanStep(tool="noop", parameters={}))
        return ExecutionPlan(steps=steps, requires_llm=False)

    @property
    def name(self) -> str:
        return "placeholder"


# Provider registry with lazy import support
_planner_providers: Dict[str, Any] = {
    "placeholder": PlaceholderPlanner,
}


def _import_provider(class_path: str):
    module_path, class_name = class_path.rsplit(".", 1)
    module = __import__(module_path, fromlist=[class_name])
    return getattr(module, class_name)


def _get_provider_class(registry: Dict, key: str):
    entry = registry.get(key)
    if not entry:
        return None
    if isinstance(entry, str):
        cls = _import_provider(entry)
        registry[key] = cls
        return cls
    return entry


def register_planner(name: str, provider_class: type) -> None:
    _planner_providers[name] = provider_class


def create_planner(config: Optional[PlannerConfig] = None) -> BasePlanner:
    cfg = config or PlannerConfig()
    provider_cls = _planner_providers.get(cfg.provider)
    if not provider_cls:
        raise PlanningError(f"Unknown planner provider: {cfg.provider}")
    if isinstance(provider_cls, str):
        provider_cls = _import_provider(provider_cls)
        _planner_providers[cfg.provider] = provider_cls
    return provider_cls(config)


def get_available_planners() -> List[str]:
    return list(_planner_providers.keys())