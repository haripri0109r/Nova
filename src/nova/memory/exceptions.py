"""
Memory Engine Exceptions
"""

from typing import Optional


class MemoryEngineError(Exception):
    """Base exception for memory engine errors."""

    def __init__(self, message: str, code: str = "MEMORY_ERROR", details: dict = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}

    def to_dict(self):
        return {
            "error": self.message,
            "code": self.code,
            "details": self.details,
        }


class MemoryNotFoundError(MemoryEngineError):
    def __init__(self, memory_id: str):
        super().__init__(
            f"Memory with id '{memory_id}' not found",
            code="MEMORY_NOT_FOUND",
            details={"memory_id": memory_id},
        )


class MemoryValidationError(MemoryEngineError):
    def __init__(self, message: str, field: str = None, value=None):
        super().__init__(
            message,
            code="VALIDATION_ERROR",
            details={"field": field, "value": str(value) if value is not None else None},
        )


class MemoryStorageError(MemoryEngineError):
    def __init__(self, message: str, operation: str = None, details: dict = None):
        super().__init__(
            message,
            code="STORAGE_ERROR",
            details={"operation": operation, **(details or {})},
        )


class MemoryExpiredError(MemoryEngineError):
    def __init__(self, memory_id: str):
        super().__init__(
            f"Memory {memory_id} has expired",
            code="MEMORY_EXPIRED",
            details={"memory_id": memory_id},
        )


class MemoryLimitExceededError(MemoryEngineError):
    def __init__(self, limit: int, current: int):
        super().__init__(
            f"Memory limit exceeded: {current}/{limit}",
            code="MEMORY_LIMIT_EXCEEDED",
            details={"limit": limit, "current": current},
        )