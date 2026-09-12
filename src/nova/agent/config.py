"""Configuration for Agent Orchestrator."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from dataclasses import dataclass, field
from pydantic import BaseModel, Field


@dataclass
class RetryPolicy:
    """Retry policy configuration."""
    max_retries: int = 3
    base_delay: float = 1.0  # seconds
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True


@dataclass
class TimeoutPolicy:
    """Timeout policy configuration."""
    default_timeout: float = 30.0  # seconds
    max_timeout: float = 300.0
    per_skill: Dict[str, float] = field(default_factory=dict)


@dataclass
class ExecutionPolicy:
    """Execution policy configuration."""
    max_concurrent_actions: int = 10
    default_parallel: bool = False
    allowed_skills: List[str] = None
    blocked_skills: List[str] = None
    max_execution_time: float = 300.0  # seconds
    allow_partial_failure: bool = False


@dataclass
class SkillConfig:
    """Per-skill configuration."""
    timeout_seconds: int = 30
    max_retries: Optional[int] = None
    retry_delay: float = 1.0
    required_permissions: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class OrchestratorConfig:
    """Main configuration for Agent Orchestrator."""
    retry_policy: RetryPolicy = None
    timeout_policy: TimeoutPolicy = None
    execution_policy: ExecutionPolicy = None
    enable_metrics: bool = True
    log_level: str = "INFO"
    max_history: int = 1000
    
    def __post_init__(self):
        if self.retry_policy is None:
            self.retry_policy = RetryPolicy()
        if self.timeout_policy is None:
            self.timeout_policy = TimeoutPolicy()
        if self.execution_policy is None:
            self.execution_policy = ExecutionPolicy()


class OrchestratorConfigModel(BaseModel):
    """Pydantic model for config validation."""
    retry_policy: Optional[dict] = None
    timeout_policy: Optional[dict] = None
    execution_policy: Optional[dict] = None
    enable_metrics: bool = True
    log_level: str = "INFO"
    max_history: int = 1000
    
    def to_dataclass(self) -> 'OrchestratorConfig':
        return OrchestratorConfig(
            retry_policy=RetryPolicy(**self.retry_policy) if self.retry_policy else None,
            timeout_policy=TimeoutPolicy(**self.timeout_policy) if self.timeout_policy else None,
            execution_policy=ExecutionPolicy(**self.execution_policy) if self.execution_policy else None,
            enable_metrics=self.enable_metrics,
            log_level=self.log_level,
            max_history=self.max_history,
        )