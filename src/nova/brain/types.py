"""
Brain Engine type definitions.
"""
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class IntentCategory(str, Enum):
    """High‑level intent categories."""
    OPEN_APPLICATION = "open_application"
    CLOSE_APPLICATION = "close_application"
    OPEN_BROWSER = "open_browser"
    SET_VOLUME = "set_volume"
    WEB_SEARCH = "web_search"
    SYSTEM_CONTROL = "system_control"
    MEDIA_CONTROL = "media_control"
    FILE_OPERATION = "file_operation"
    GENERAL_CONVERSATION = "general_conversation"
    SCREEN_READ = "screen_read"
    TASK_CONTROL = "task_control"
    TASK_QUERY = "task_query"
    UNKNOWN = "unknown"


class ConfidenceLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ExecutionMode(str, Enum):
    """How the request should be executed."""
    DIRECT_TOOL = "direct_tool"          # no LLM needed
    LLM_ASSISTED = "llm_assisted"        # needs LLM reasoning
    HYBRID = "hybrid"                    # mix of both


class BrainConfig(BaseModel):
    """Top‑level configuration for the Brain Engine."""
    intent_classifier: "IntentClassifierConfig" = Field(default_factory=lambda: IntentClassifierConfig())
    planner: "PlannerConfig" = Field(default_factory=lambda: PlannerConfig())
    router: "RouterConfig" = Field(default_factory=lambda: RouterConfig())
    enable_llm_fallback: bool = True
    default_confidence_threshold: float = 0.6


class IntentClassifierConfig(BaseModel):
    provider: str = "placeholder"
    model_path: Optional[str] = None
    confidence_threshold: float = 0.6
    extra: Dict[str, Any] = Field(default_factory=dict)


class PlannerConfig(BaseModel):
    provider: str = "placeholder"
    max_steps: int = 5
    enable_llm: bool = True
    extra: Dict[str, Any] = Field(default_factory=dict)


class RouterConfig(BaseModel):
    provider: str = "placeholder"
    default_target: str = "agent_orchestrator"
    extra: Dict[str, Any] = Field(default_factory=dict)