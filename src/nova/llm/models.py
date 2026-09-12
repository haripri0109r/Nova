"""LLM Engine – pure data models (single source of truth)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from .types import LLMProvider, LLMTaskType


# -------------------------------------------------------------------------
# Core message / request / response models
# -------------------------------------------------------------------------
class LLMMessage(BaseModel):
    """A single message in a conversation."""
    role: str                     # "system" | "user" | "assistant" | "tool"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class LLMRequest(BaseModel):
    """Request sent to an LLM provider."""
    messages: List[LLMMessage]
    task_type: LLMTaskType = LLMTaskType.CONVERSATION
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int = Field(default=2048, gt=0)
    top_p: float = Field(default=1.0, ge=0.0, le=1.0)
    stop_sequences: List[str] = Field(default_factory=list)
    tools: Optional[List[Dict[str, Any]]] = None
    tool_choice: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    stream: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LLMResponse(BaseModel):
    """Raw response returned by an LLM provider."""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Dict[str, int] = Field(default_factory=dict)
    model: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ToolAction(BaseModel):
    """A concrete tool/action the LLM may request."""
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class StructuredResponse(BaseModel):
    """Strict JSON structure the LLM must return."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)


# Compatibility aliases
LLMResponseStructured = StructuredResponse
LLMAction = ToolAction


class ToolAction(BaseModel):
    """A concrete tool/action the LLM may request."""
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class StructuredResponse(BaseModel):
    """Strict JSON structure the LLM must return."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)


# Compatibility aliases
LLMResponseStructured = StructuredResponse
LLMAction = ToolAction


class LLMActionResult(BaseModel):
    """Result of executing a tool action."""
    tool: str
    success: bool
    result: Any = None
    error: Optional[str] = None


class ExecutionRequest(BaseModel):
    """Request coming from the Brain → LLM Engine."""
    text: str
    session_id: str = "default"
    context: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResponse(BaseModel):
    """Structured response returned to the Brain / Agent layer."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)
    provider: Optional[str] = None
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Result of executing a plan returned to the caller."""
    success: bool
    results: List[LLMActionResult] = Field(default_factory=list)
    error: Optional[str] = None
    total_time_ms: int = 0


class LLMActionResult(BaseModel):
    """Result of executing a tool action (alias for ExecutionResult item)."""
    tool: str
    success: bool
    result: Any = None
    error: Optional[str] = None


# -------------------------------------------------------------------------
# Conversation / context models
# -------------------------------------------------------------------------
class ConversationContext(BaseModel):
    """Context object passed around during a conversation."""
    session_id: str
    messages: List[LLMMessage] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ConversationTurn(BaseModel):
    """One turn in a dialogue – kept only for optional history."""
    role: str
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConversationMemory(BaseModel):
    """Simple container for a full conversation history."""
    turns: List[ConversationTurn] = Field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append(ConversationTurn(role=role, content=content))


# -------------------------------------------------------------------------
# Exported symbols
# -------------------------------------------------------------------------
__all__ = [
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "ToolAction",
    "StructuredResponse",
    "LLMResponseStructured",
    "LLMAction",
    "LLMActionResult",
    "ExecutionRequest",
    "ExecutionResponse",
    "ExecutionResult",
    "ConversationContext",
    "ConversationTurn",
    "ConversationMemory",
]