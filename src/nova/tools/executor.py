"""
ToolExecutor – executes registered tools by name.
"""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nova.tools.executor")


class ToolExecutor:
    """
    Registry and executor for tools.
    Tools can be sync or async callables.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Callable[..., Any]] = {}

    def register(self, name: str, tool: Callable[..., Any]) -> None:
        """Register a tool by name."""
        if name in self._tools:
            logger.warning("Overwriting existing tool: %s", name)
        self._tools[name] = tool
        logger.debug("Registered tool: %s", name)

    def unregister(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if tool was found."""
        if name in self._tools:
            del self._tools[name]
            return True
        return False

    def has_tool(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    def get_tool(self, name: str) -> Optional[Callable[..., Any]]:
        """Get a tool by name."""
        return self._tools.get(name)

    async def execute(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """Execute a registered tool by name."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool not found: {name}")
        
        # If called with a single dict argument, pass it as-is
        # Otherwise pass args/kwargs normally
        if len(args) == 1 and not kwargs and isinstance(args[0], dict):
            call_args = args[0]
            if asyncio.iscoroutinefunction(tool):
                return await tool(call_args)
            else:
                # Run sync tool in thread pool to avoid blocking event loop
                return await asyncio.to_thread(tool, call_args)
        else:
            if asyncio.iscoroutinefunction(tool):
                return await tool(*args, **kwargs)
            else:
                # Run sync tool in thread pool to avoid blocking event loop
                return await asyncio.to_thread(tool, *args, **kwargs)

    async def execute_with_context(self, name: str, context: Dict[str, Any]) -> Any:
        """Execute a tool with a context dict as keyword arguments."""
        tool = self._tools.get(name)
        if tool is None:
            raise KeyError(f"Tool not found: {name}")
        
        if asyncio.iscoroutinefunction(tool):
            return await tool(**context)
        else:
            # Run sync tool in thread pool to avoid blocking event loop
            return await asyncio.to_thread(tool, **context)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())


# Singleton instance
_tool_executor: Optional[ToolExecutor] = None


def get_tool_executor() -> ToolExecutor:
    """Get or create the global ToolExecutor instance."""
    global _tool_executor
    if _tool_executor is None:
        _tool_executor = ToolExecutor()
    return _tool_executor


__all__ = ["ToolExecutor", "get_tool_executor"]