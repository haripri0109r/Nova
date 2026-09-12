"""Execution context and context manager."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional
from .models import SkillContext

@dataclass
class ExecutionContext:
    """Execution context for plan execution."""
    session_id: str
    execution_id: str
    user_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_skill_context(self, skill_name: str) -> SkillContext:
        """Convert to skill-specific context."""
        return SkillContext(
            session_id=self.session_id,
            execution_id=self.execution_id,
            metadata={
                **self.metadata,
                "user_id": self.user_id,
                "skill": skill_name
            }
        )