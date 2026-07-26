"""
Automatic registry for domain controllers.
"""

import logging
from typing import Dict, List, Type

from .base import BaseController

logger = logging.getLogger("nova.controllers.registry")


class ControllerRegistry:
    """Singleton registry that holds instantiated controllers."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._controllers: Dict[str, BaseController] = {}
        return cls._instance

    def register(self, controller: BaseController) -> None:
        """Register a controller instance."""
        if controller.domain in self._controllers:
            logger.warning(
                "Controller for domain %r already registered (%s), overwriting.",
                controller.domain,
                self._controllers[controller.domain],
            )
        self._controllers[controller.domain] = controller
        logger.debug("Registered controller %s for domain %r", controller, controller.domain)

    def get(self, domain: str) -> BaseController | None:
        """Retrieve a controller by its domain name."""
        return self._controllers.get(domain)

    def all(self) -> List[BaseController]:
        """Return all registered controllers."""
        return list(self._controllers.values())


# Global singleton
registry = ControllerRegistry()