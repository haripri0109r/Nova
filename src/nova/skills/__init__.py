"""
Nova Skills Package
"""

from .base import BaseSkill
from .registry import SkillRegistry, registry
from .manager import SkillManager

# Import sub‑packages so that skills auto‑register
from . import system, applications, browser, media, files, screen  # noqa: F401

__all__ = [
    "BaseSkill",
    "SkillRegistry",
    "registry",
    "SkillManager",
]