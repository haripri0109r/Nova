"""Strict Pydantic models – **only** the data structures Nova needs."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from .types import LLMProvider, LLMTaskType
from .config import LLMConfig


class ToolAction(BaseModel):
    """One concrete tool the Agent Orchestrator can execute."""
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class LLMAction(ToolAction):
    """Alias for compatibility."""
    pass


class StructuredResponse(BaseModel):
    """The **exact** JSON the LLM must return – no extra keys."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)


class LLMResponseStructured(StructuredResponse):
    """Alias for compatibility."""
    pass


class LLMActionResult(BaseModel):
    """Result of executing a tool action."""
    tool: str
    success: bool
    result: Any = None
    error: Optional[str] = None


class LLMMessage(BaseModel):
    """A single message in a conversation."""
    role: str          # "system" | "user" | "assistant" | "tool"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ConversationContext(BaseModel):
    """A conversation session with history."""
    session_id: str
    messages: List[LLMMessage] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def add_message(self, message: LLMMessage) -> None:
        self.messages.append(message)
        self.updated_at = datetime.utcnow()

    def get_recent(self, limit: int = 10) -> List[LLMMessage]:
        return self.messages[-limit:]


class ConversationTurn(BaseModel):
    """One turn in a dialogue – kept only for optional history."""
    role: str          # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConversationMemory(BaseModel):
    """Simple container for a full conversation history."""
    turns: List[ConversationTurn] = Field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append(ConversationTurn(role=role, content=content))


class LLMMessage(BaseModel):
    """A single message in a conversation."""
    role: str          # "system" | "user" | "assistant" | "tool"
    content: str
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None


class ConversationContext(BaseModel):
    """A conversation session with history."""
    session_id: str
    messages: List[LLMMessage] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def add_message(self, message: LLMMessage) -> None:
        self.messages.append(message)
        self.updated_at = datetime.utcnow()

    def get_recent(self, limit: int = 10) -> List[LLMMessage]:
        return self.messages[-limit:]


class ConversationTurn(BaseModel):
    """One turn in a dialogue – kept only for optional history."""
    role: str          # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConversationMemory(BaseModel):
    """Simple container for a full conversation history."""
    turns: List[ConversationTurn] = Field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append(ConversationTurn(role=role, content=content))


class LLMRequest(BaseModel):
    """Request to an LLM provider."""
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
    """Raw response from LLM provider."""
    content: str = ""
    tool_calls: List[Dict[str, Any]] = Field(default_factory=list)
    finish_reason: Optional[str] = None
    usage: Dict[str, int] = Field(default_factory=dict)
    model: Optional[str] = None
    provider: Optional[str] = None
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LLMResponseStructured(BaseModel):
    """The **exact** JSON the LLM must return – no extra keys."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)


class LLMActionResult(BaseModel):
    """Result of executing a tool action."""
    tool: str
    success: bool
    result: Any = None
    error: Optional[str] = None


class ToolAction(BaseModel):
    """One concrete tool the Agent Orchestrator can execute."""
    tool: str
    parameters: Dict[str, Any] = Field(default_factory=dict)
    description: str = ""


class LLMAction(ToolAction):
    """Alias for compatibility."""
    pass


class StructuredResponse(BaseModel):
    """The **exact** JSON the LLM must return – no extra keys."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)


class LLMResponseStructured(StructuredResponse):
    """Alias for compatibility."""
    pass


class LLMActionResult(BaseModel):
    """Result of executing a tool action."""
    tool: str
    success: bool
    result: Any = None
    error: Optional[str] = None


class ExecutionRequest(BaseModel):
    """What the Brain Engine sends us."""
    text: str
    session_id: str = "default"
    context: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResponse(BaseModel):
    """What we give back to the Brain Engine → Agent Orchestrator."""
    requires_execution: bool
    response_text: str
    actions: List[ToolAction] = Field(default_factory=list)
    provider: Optional[LLMProvider] = None
    latency_ms: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ExecutionResult(BaseModel):
    """Result of executing a plan."""
    success: bool
    results: List[LLMActionResult] = Field(default_factory=list)
    error: Optional[str] = None
    total_time_ms: int = 0


class ConversationTurn(BaseModel):
    """One turn in a dialogue – kept only for optional history."""
    role: str          # "user" | "assistant"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConversationMemory(BaseModel):
    """Simple container for a full conversation history."""
    turns: List[ConversationTurn] = Field(default_factory=list)

    def add_turn(self, role: str, content: str) -> None:
        self.turns.append(ConversationTurn(role=role, content=content))