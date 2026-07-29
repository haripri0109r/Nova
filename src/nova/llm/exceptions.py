"""All LLM‑engine specific errors – single inheritance tree."""
from typing import Any, Dict, Optional


class LLMEngineError(Exception):
    def __init__(self, msg: str, code: str = "LLM_ERROR", details: Optional[Dict[str, Any]] = None):
        super().__init__(msg)
        self.code = code
        self.details = details or {}


class ProviderError(LLMEngineError):
    def __init__(self, msg: str, provider: str, **kw):
        super().__init__(msg, code="PROVIDER_ERROR", details={"provider": provider, **kw})


class ParseError(LLMEngineError):
    def __init__(self, msg: str, raw: str = "", **kw):
        super().__init__(msg, code="PARSE_ERROR", details={"raw": raw, **kw})


class ValidationError(LLMEngineError):
    def __init__(self, msg: str, field: str = "", **kw):
        super().__init__(msg, code="VALIDATION_ERROR", details={"field": field, **kw})


# Aliases for backward compatibility / public API
LLMParseError = ParseError
LLMValidationError = ValidationError
LLMProviderError = ProviderError
LLMConfigurationError = LLMEngineError
LLMTimeoutError = LLMEngineError
LLMQuotaExceededError = LLMEngineError