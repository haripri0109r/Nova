"""
Condition evaluation for workflow branching.
"""
from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from typing import Any, Dict, Callable, Awaitable, Union
from pydantic import BaseModel, ConfigDict


class Condition(ABC, BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    @abstractmethod
    async def evaluate(self, context: Dict[str, Any]) -> bool:
        """Return True if condition satisfied."""
        ...


class ExpressionCondition(Condition):
    """
    Evaluates a simple expression string against context using safe eval.
    Example expression: "context['battery'] < 20"
    """
    expression: str

    async def evaluate(self, context: Dict[str, Any]) -> bool:
        # Very small safe eval: only allow access to context dict
        try:
            # Provide only context as variable
            return bool(eval(self.expression, {"__builtins__": {}}, {"context": context}))
        except Exception:
            return False


class PythonCondition(Condition):
    """
    Uses a user-provided callable (sync or async) that receives context and returns bool.
    """
    callable: Callable[[Dict[str, Any]], Union[bool, Awaitable[bool]]]

    async def evaluate(self, context: Dict[str, Any]) -> bool:
        result = self.callable(context)
        if asyncio.iscoroutine(result):
            return await result
        return bool(result)