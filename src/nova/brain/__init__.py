"""
Nova Brain Package – Public API.
"""
from .engine import BrainEngine, get_brain_engine, BrainEngineConfig
from .models import (
    RecognizedInput,
    IntentResult,
    PlanStep,
    ExecutionPlan,
    RoutingDecision,
    BrainResponse,
)
from .intent_classifier import (
    BaseIntentClassifier,
    PlaceholderIntentClassifier,
    create_intent_classifier,
    IntentClassifierConfig,
)
from .planner import (
    Planner,
    get_planner,
)
from .router import (
    BaseRouter,
    PlaceholderRouter,
    create_router,
    RouterConfig,
)
from .config import BrainEngineConfig, IntentClassifierConfig, PlannerConfig, RouterConfig
from .exceptions import (
    BrainEngineError,
    IntentClassificationError,
    PlanningError,
    RoutingError,
    LLMError,
)

# Alias for backward compatibility
get_brain = get_brain_engine

__all__ = [
    "BrainEngine",
    "get_brain_engine",
    "get_brain",
    "BrainEngineConfig",
    "RecognizedInput",
    "IntentResult",
    "PlanStep",
    "ExecutionPlan",
    "RoutingDecision",
    "BrainResponse",
    "BaseIntentClassifier",
    "PlaceholderIntentClassifier",
    "create_intent_classifier",
    "IntentClassifierConfig",
    "Planner",
    "get_planner",
    "BaseRouter",
    "PlaceholderRouter",
    "create_router",
    "RouterConfig",
    "BrainEngineConfig",
    "IntentClassifierConfig",
    "PlannerConfig",
    "RouterConfig",
    "BrainEngineError",
    "IntentClassificationError",
    "PlanningError",
    "RoutingError",
    "LLMError",
]