"""
Brain Engine exceptions.
"""
from typing import Any, Dict, Optional


class BrainEngineError(Exception):
    """Base exception for brain engine errors."""
    def __init__(self, message: str, code: str = "BRAIN_ERROR", details: Dict[str, Any] = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self) -> dict:
        return {"error": self.message, "code": self.code, "details": self.details}


class IntentClassificationError(BrainEngineError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, code="INTENT_CLASSIFICATION_ERROR", details=details)


class PlanningError(BrainEngineError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, code="PLANNING_ERROR", details=details)


class RoutingError(BrainEngineError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, code="ROUTING_ERROR", details=details)


class LLMError(BrainEngineError):
    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, code="LLM_ERROR", details=details)