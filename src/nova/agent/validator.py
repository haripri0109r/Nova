"""Validation logic for skill execution."""
from __future__ import annotations
from typing import Dict, List, Any, Optional
from .models import ExecutionRequest, ToolAction, ValidationResult
from .registry import get_skill_registry
from .exceptions import SkillNotFoundError, ValidationError
from .registry import get_skill_registry

import logging
logger = logging.getLogger("nova.agent.validator")


class ActionValidator:
    """Validates action requests before execution."""

    def __init__(self):
        self._registry = get_skill_registry()

    async def validate(self, request: 'ExecutionRequest') -> 'ValidationResult':
        """Validate an execution request."""
        errors = []
        
        if not request.actions:
            return ValidationResult(valid=False, errors=["No actions provided"])
        
        for i, action in enumerate(request.actions):
            action_errors = self._validate_action(action, i)
            errors.extend(action_errors)
        
        return ValidationResult(
            valid=len(errors) == 0,
            errors=errors
        )

    def _validate_action(self, action, index: int) -> List[str]:
        """Validate a single action."""
        errors = []
        
        # Check if tool exists
        if not hasattr(action, 'tool') or not action.tool:
            errors.append(f"Action {index}: missing tool name")
            return errors
        
        # Check if tool exists in registry
        try:
            skill = get_skill_registry().get(action.tool)
        except Exception:
            pass
        else:
            # Skill exists, validate parameters
            if hasattr(skill, 'validate'):
                try:
                    skill.validate(action.parameters)
                except Exception as e:
                    errors.append(f"Action {index} ({action.tool}): {str(e)}")
        
        # Check for duplicate execution if needed
        # Could add deduplication logic here
        
        return errors


class ValidationResult:
    """Result of validation."""
    def __init__(self, valid: bool, errors: list):
        self.valid = valid
        self.errors = errors
    
    def __bool__(self):
        return self.valid
    
    def __str__(self):
        return f"ValidationResult(valid={self.valid}, errors={self.errors})"