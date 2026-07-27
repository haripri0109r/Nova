"""
Memory Engine Manager - Singleton factory for MemoryEngine.
"""
from __future__ import annotations

from typing import Optional
from .engine import MemoryEngine
from ..config import settings

_engine: Optional["MemoryEngine"] = None


async def get_memory_engine(
    store=None,
    embedding_provider=None,
    default_scope: str = "short_term",
    default_type: str = "conversation",
    default_importance: float = 1.0,
    auto_cleanup: bool = True,
    cleanup_interval: int = 300,
) -> "MemoryEngine":
    """
    Get or create the global MemoryEngine instance.
    
    Args:
        store: Optional custom storage backend
        embedding_provider: Optional embedding provider
        default_scope: Default memory scope
        default_type: Default memory type
        default_importance: Default importance value
        auto_cleanup: Enable automatic cleanup
        cleanup_interval: Cleanup interval in seconds
        
    Returns:
        MemoryEngine singleton instance
    """
    global _engine
    if _engine is None:
        _engine = MemoryEngine(
            store=None,
            embedding_provider=None,
            default_scope="short_term",
            default_type="conversation",
            default_importance=1.0,
            auto_cleanup=True,
            cleanup_interval=300,
        )
        await _engine.initialize()
    return _engine


async def close_memory_engine():
    """Close and cleanup the global memory engine."""
    global _engine
    if _engine is not None:
        await _engine.cleanup()
        _engine = None


async def initialize_memory_engine(
    store=None,
    embedding_provider=None,
    default_scope: str = "short_term",
    default_type: str = "conversation",
    default_importance: float = 1.0,
    auto_cleanup: bool = True,
    cleanup_interval: int = 300,
) -> "MemoryEngine":
    """Initialize the global memory engine."""
    global _engine
    if _engine is not None:
        return _engine
    
    _engine = MemoryEngine(
        store=None,
        embedding_provider=None,
        default_scope="short_term",
        default_type="conversation",
        default_importance=1.0,
        auto_cleanup=True,
        cleanup_interval=300,
    )
    await _engine.initialize()
    return _engine


# Backward compatibility
get_memory_engine = get_memory_engine
close_memory_engine = close_memory_engine
initialize_memory_engine = initialize_memory_engine