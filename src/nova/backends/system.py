"""
System backend – power actions (shutdown, restart, sleep).
"""
from __future__ import annotations
import logging
from typing import Any, Dict

log = logging.getLogger("nova.backends.system")

def handle(payload: Dict) -> Any:
    """Execute power command."""
    # TODO: implement via subprocess / ctypes
    raise NotImplementedError