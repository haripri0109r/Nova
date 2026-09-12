"""
Base class for all Nova skills.
"""

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Union, Awaitable

logger = logging.getLogger("nova.skills")


class BaseSkill(ABC):
    """
    Every skill must inherit from this class and implement the abstract methods.
    """

    # The primary intent this skill handles, e.g. "set_volume"
    intent: str = ""

    # Human‑readable description for debugging / help
    description: str = ""

    def __init__(self) -> None:
        self.logger = logging.getLogger(f"nova.skills.{self.__class__.__name__}")

    @abstractmethod
    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        """
        Return True if this skill can process the given intent dictionary.
        Typically checks intent_data["intent"] == self.intent and possibly
        additional fields such as action.
        """
        ...

    @abstractmethod
    def execute(self, intent_data: Dict[str, Any]) -> Union[Dict[str, Any], Awaitable[Dict[str, Any]]]:
        """
        Perform the actual work. Must return a result dictionary (or an awaitable
        resolving to one) that will be sent back to the caller
        (e.g. {"status": "ok", "detail": "volume set to 30"}).
        Should raise exceptions only for unrecoverable errors.
        """
        ...

    def __repr__(self) -> str:
        return f"<Skill {self.__class__.__name__} intent={self.intent!r}>"