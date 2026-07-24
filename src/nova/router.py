"""
Command Router – maps structured intent dicts to backend handlers.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, Optional

log = logging.getLogger("nova.router")

Handler = Callable[[Dict], Any]

class Router:
    """Minimal dispatch table."""
    def __init__(self) -> None:
        self._routes: Dict[str, Handler] = {}

    def register(self, intent_prefix: str, handler: Handler) -> None:
        """Register handler for a top‑level intent prefix (e.g. 'settings')."""
        # TODO: implement registration logic
        pass

    def route(self, payload: Dict) -> Any:
        """Dispatch payload to the appropriate backend."""
        # TODO: implement routing logic
        raise NotImplementedError


_router: Optional["Router"] = None

def get_router() -> Router:
    """Return process‑wide Router instance."""
    global _router
    if _router is None:
        _router = Router()
        _register_default_routes(_router)
    return _router

def route(payload: Dict) -> Any:
    """Convenience wrapper."""
    return get_router().route(payload)

def _register_default_routes(r: Router) -> None:
    """Wire default backends."""
    # TODO: import backends and register
    pass