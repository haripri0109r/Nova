"""LLM Engine exception hierarchy – compatible with existing code."""
from __future__ import annotations

from typing import Any, Dict, Optional


class LLMEngineError(Exception):
    """Base exception for all LLM engine errors."""

    def __init__(
        self,
        message: str,
        error_code: str = "LLM_ERROR",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        # compatibility alias
        self.code = error_code
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "message": self.message,
            "error_code": self.error_code,
            "details": self.details,
        }


class LLMConfigurationError(LLMEngineError):
    """Raised when LLM engine configuration is invalid."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="CONFIGURATION_ERROR", details=details)


class LLMProviderError(LLMEngineError):
    """Raised when a provider reports an error."""

    def __init__(
        self,
        message: str,
        provider: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message,
            error_code="PROVIDER_ERROR",
            details={"provider": provider, **(details or {})},
        )


class LLMGenerationError(LLMEngineError):
    """Raised when the LLM fails to generate a response."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="GENERATION_ERROR", details=details)


class LLMValidationError(LLMEngineError):
    """Raised when LLM output fails validation."""

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message,
            error_code="VALIDATION_ERROR",
            details={"field": field, **(details or {})},
        )


class LLMTimeoutError(LLMEngineError):
    """Raised when an LLM request times out."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="TIMEOUT_ERROR", details=details)


class LLMParsingError(LLMEngineError):
    """Raised when LLM output cannot be parsed."""

    def __init__(self, message: str, raw: str = "", details: Optional[Dict[str, Any]] = None):
        super().__init__(
            message,
            error_code="PARSE_ERROR",
            details={"raw": raw, **(details or {})},
        )


class LLMConversationError(LLMEngineError):
    """Raised when conversation handling fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="CONVERSATION_ERROR", details=details)


class LLMContextError(LLMEngineError):
    """Raised when context building fails."""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, error_code="CONTEXT_ERROR", details=details)


# ----------------------------------------------------------------------
# Backward‑compatibility aliases (used by existing code)
# ----------------------------------------------------------------------
ProviderError = LLMProviderError
ParseError = LLMParsingError
ValidationError = LLMValidationError
LLMParseError = LLMParsingError
LLMValidationError = LLMValidationError
LLMProviderError = LLMProviderError
LLMConfigurationError = LLMConfigurationError
LLMTimeoutError = LLMTimeoutError
LLMQuotaExceededError = LLMEngineError  # legacy alias, generic error

__all__ = [
    "LLMEngineError",
    "LLMConfigurationError",
    "LLMProviderError",
    "LLMGenerationError",
    "LLMValidationError",
    "LLMTimeoutError",
    "LLMParsingError",
    "LLMConversationError",
    "LLMContextError",
    # compatibility aliases
    "ProviderError",
    "ParseError",
    "ValidationError",
    "LLMParseError",
    "LLMValidationError",
    "LLMProviderError",
    "LLMConfigurationError",
    "LLMTimeoutError",
    "LLMQuotaExceededError",
]