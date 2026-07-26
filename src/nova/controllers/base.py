"""
Base class for all Nova controllers.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict

logger = logging.getLogger("nova.controllers")


class BaseController(ABC):
    """
    Every concrete controller must subclass this and implement the abstract methods.
    """

    # The primary intent domain this controller handles, e.g. "shutdown"
    intent: str = ""

    # Human readable description for debugging / help
    description: str = ""

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"nova.controllers.{self.__class__.__name__}")

    @abstractmethod
    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        """
        Return True if this controller can process the given intent dictionary.
        Typically checks intent_data["intent"] == self.intent and possibly additional fields.
        """
        ...

    @abstractmethod
    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Perform the actual work. Must return a result dictionary that will be sent back
        to the caller (e.g. {"status": "ok", "detail": "Volume set to 30%"}).
        Should raise exceptions only for unrecoverable errors.
        """
        ...

    def __repr__(self) -> str:
        return f"<Controller {self.__class__.__name__} intent={self.intent!r}>"