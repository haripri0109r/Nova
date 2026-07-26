"""
Nova Controllers Package

Auto‑imports all concrete controllers so they self‑register.
"""

from .base import BaseController
from .registry import ControllerRegistry, registry
from .manager import ControllerManager, get_controller_manager

# Import sub‑modules to trigger auto‑registration
from . import (
    system,
    display,
    audio,
    network,
    personalization,
    privacy,
    applications,
    browser,
    media,
    files,
    windows,
    power,
)  # noqa: F401

__all__ = [
    "BaseController",
    "ControllerRegistry",
    "registry",
    "ControllerManager",
    "get_controller_manager",
]