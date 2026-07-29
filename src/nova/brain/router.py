"""
Routing abstraction and placeholder implementation.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from .models import BrainDecision, IntentResult, ExecutionPlan
from .types import RouterConfig
from .exceptions import RoutingError


class BaseRouter(ABC):
    """Abstract router."""

    def __init__(self, config: Optional[RouterConfig] = None):
        self.config = config or RouterConfig()
        self._initialized = False

    @abstractmethod
    async def initialize(self) -> bool:
        ...

    @abstractmethod
    async def cleanup(self) -> None:
        ...

    @abstractmethod
    async def route(self, intent: IntentResult, plan: ExecutionPlan) -> str:
        """Return target subsystem name, e.g. 'agent_orchestrator'."""
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    def is_initialized(self) -> bool:
        return self._initialized


class PlaceholderRouter(BaseRouter):
    def __init__(self, config: Optional[RouterConfig] = None):
        super().__init__(config)

    async def initialize(self) -> bool:
        self._initialized = True
        return True

    async def cleanup(self) -> None:
        self._initialized = False

    async def route(self, intent: IntentResult, plan: ExecutionPlan) -> str:
        # Simple rule: if requires LLM -> agent_orchestrator, else skill_manager
        if plan.requires_llm:
            return "agent_orchestrator"
        return "skill_manager"

    @property
    def name(self) -> str:
        return "placeholder"


# Registry
_router_providers: Dict[str, Any] = {
    "placeholder": PlaceholderRouter,
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


def register_router(name: str, provider_class: type) -> None:
    _router_providers[name] = provider_class


def create_router(config: Optional[RouterConfig] = None) -> BaseRouter:
    cfg = config or RouterConfig()
    provider_cls = _router_providers.get(cfg.provider)
    if not provider_cls:
        raise RoutingError(f"Unknown router provider: {cfg.provider}")
    if isinstance(provider_cls, str):
        provider_cls = _import_provider(provider_cls)
        _router_providers[cfg.provider] = provider_cls
    return provider_cls(config)


def get_available_routers() -> List[str]:
    return list(_router_providers.keys())