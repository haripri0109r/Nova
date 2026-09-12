"""Memory Engine Exceptions."""

from typing import Optional, Dict, Any


class MemoryEngineError(Exception):
    """Base exception for memory engine errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "MEMORY_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class MemoryConfigurationError(MemoryEngineError):
    """Raised when memory engine configuration is invalid."""
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)


class MemoryValidationError(MemoryEngineError):
    def __init__(self, message: str, field: Optional[str] = None, value: Any = None):
        super().__init__(
            message,
            error_code="VALIDATION_ERROR",
            details={"field": field, "value": str(value) if value is not None else None},
        )


class MemoryStorageError(MemoryEngineError):
    def __init__(self, message: str, operation: Optional[str] = None, details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            error_code="STORAGE_ERROR",
            details={"operation": operation, **(details or {})},
        )


class MemoryRetrievalError(MemoryEngineError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="RETRIEVAL_ERROR", details=details)


class MemoryEmbeddingError(MemoryEngineError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="EMBEDDING_ERROR", details=details)


class MemoryProcessorError(MemoryEngineError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="PROCESSOR_ERROR", details=details)


class MemoryTimeoutError(MemoryEngineError):
    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="TIMEOUT_ERROR", details=details)


class MemoryExpiredError(MemoryEngineError):
    def __init__(self, memory_id: str):
        super().__init__(
            f"Memory {memory_id} has expired",
            error_code="MEMORY_EXPIRED",
            details={"memory_id": memory_id},
        )


class MemoryNotFoundError(MemoryEngineError):
    def __init__(self, memory_id: str):
        super().__init__(
            f"Memory with id '{memory_id}' not found",
            error_code="MEMORY_NOT_FOUND",
            details={"memory_id": memory_id},
        )


class MemoryLimitExceededError(MemoryEngineError):
    def __init__(self, limit: int, current: int):
        super().__init__(
            f"Memory limit exceeded: {current}/{limit}",
            error_code="MEMORY_LIMIT_EXCEEDED",
            details={"limit": limit, "current": current},
        )


__all__ = [
    "MemoryEngineError",
    "MemoryConfigurationError",
    "MemoryValidationError",
    "MemoryStorageError",
    "MemoryRetrievalError",
    "MemoryEmbeddingError",
    "MemoryProcessorError",
    "MemoryTimeoutError",
    "MemoryExpiredError",
    "MemoryNotFoundError",
    "MemoryLimitExceededError",
]