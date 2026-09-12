"""
Screen context builder - combines accessibility information into structured context.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Set
from dataclasses import dataclass

from .elements import ScreenElement, ScreenContext, BoundingBox
from .accessibility import WindowsAccessibility, get_accessibility

logger = logging.getLogger("nova.screen.context")


# Roles considered useful for screen context
USEFUL_ROLES = {
    "Button", "Hyperlink", "Text", "Edit", "CheckBox", "RadioButton",
    "ComboBox", "ListItem", "TabItem", "MenuItem", "TreeItem",
    "Slider", "Spinner", "ProgressBar", "StatusBar", "ToolBar",
    "MenuBar", "Menu", "Tab", "Header", "HeaderItem", "Table",
    "DataGrid", "List", "Tree", "Document", "Pane", "Window",
}

# Roles to skip (usually containers with no direct user value)
SKIP_ROLES = {
    "Group", "Separator", "ScrollBar", "Thumb", "TitleBar",
    "ToolTip", "Sound", "Cursor", "Caret", "Custom",
}

# Minimum text length to consider
MIN_TEXT_LENGTH = 2


class ScreenContextBuilder:
    """
    Builds a structured ScreenContext from Windows UI Automation data.
    
    The builder discovers UI elements from the active window and builds
    a structured ScreenContext containing application info, elements,
    and visible text.
    """

    def __init__(
        self,
        accessibility: Optional["WindowsAccessibility"] = None,
        max_elements: int = 200,
        max_depth: int = 10,
    ):
        """
        Initialize the builder.
        
        Args:
            accessibility: Optional WindowsAccessibility instance (creates default if None)
            max_elements: Maximum number of elements to include in context
            max_depth: Maximum depth for UI tree traversal
        """
        self.accessibility = accessibility or get_accessibility()
        self.max_elements = max_elements
        self.max_depth = max_depth

    def build(self) -> "ScreenContext":
        """
        Build a complete ScreenContext from the active window.
        
        Returns:
            ScreenContext with application info, elements, and visible text
        """
        from .elements import ScreenContext, ScreenElement
        
        # Get accessibility instance
        if not self.accessibility.is_available():
            logger.warning("UI Automation not available - returning empty context")
            return ScreenContext()

        try:
            # Get active window info
            window_info = self.accessibility.get_foreground_window_info()
            if not window_info:
                logger.warning("No active window found")
                return ScreenContext()

            # Use process name for application detection (more reliable)
            application = window_info.get("process_name", "") or window_info.get("class_name", "Unknown")
            window_title = window_info.get("title", "")

            # Get UI elements from active window
            elements = self.accessibility.get_active_window_elements(max_depth=self.max_depth)

            # Filter and limit elements
            elements = self._filter_elements(elements)

            # Get active (focused) element from UI Automation
            active_element = self._find_focused_element(elements)

            # Extract visible text
            visible_text = self.accessibility.extract_visible_text(elements)

            # Build context
            context = ScreenContext(
                application=window_info.get("process_name", "") or "Unknown",
                window_title=window_info.get("title", ""),
                active_element=active_element,
                elements=elements[:self.max_elements],
                visible_text=visible_text,
            )

            logger.debug(
                f"Built ScreenContext: app='{context.application}', "
                f"title='{context.window_title}', elements={len(context.elements)}, "
                f"focused={'yes' if active_element else 'none'}"
            )

            return context

        except Exception as e:
            logger.error(f"Failed to build ScreenContext: {e}")
            return ScreenContext()

    def _filter_elements(self, elements: List["ScreenElement"]) -> List["ScreenElement"]:
        """
        Filter and prioritize elements for the context.
        """
        from .elements import ScreenElement
        
        filtered = []
        seen: Set[tuple] = set()  # Deduplication key: (role, name, bbox)
        
        for elem in elements:
            # Skip elements with skip roles
            if elem.role in SKIP_ROLES:
                continue

            # Skip invisible or disabled elements unless they have useful text
            if not elem.visible and not (elem.text and len(elem.text) >= MIN_TEXT_LENGTH):
                continue
            if not elem.enabled and not (elem.text and len(elem.text) >= MIN_TEXT_LENGTH):
                continue

            # Skip elements with no useful information
            if not elem.name and not elem.text and not elem.automation_id and not elem.value:
                if elem.role not in USEFUL_ROLES:
                    continue

            # Deduplication
            bbox_key = elem.bbox if elem.bbox else (0, 0, 0, 0)
            dedup_key = (elem.role, elem.name.strip().lower(), elem.text.strip().lower(), bbox_key)
            if dedup_key in seen:
                continue
            seen.add(dedup_key)

            filtered.append(elem)

        # Sort by relevance: clickable first, then by area (larger first)
        filtered.sort(key=lambda e: (
            not e.clickable,  # clickable first
            -e.area if e.area > 0 else 0,  # larger elements first
            len(e.name) + len(e.text)  # more text first
        ))

        return filtered

    def _find_focused_element(self, elements: List["ScreenElement"]) -> Optional["ScreenElement"]:
        """Find the currently focused element from UI Automation."""
        # Prefer elements that are actually focused (from UI Automation)
        for elem in elements:
            if elem.focused:
                return elem
        # No focused element found - return None (don't fake it)
        return None


__all__ = ["ScreenContextBuilder"]