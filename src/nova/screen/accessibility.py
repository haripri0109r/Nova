"""Windows UI Automation accessibility layer.
Provides read-only access to UI elements via Windows UI Automation.
"""
from __future__ import annotations

import logging
from typing import List, Optional, Any
from dataclasses import dataclass

from .elements import ScreenElement, BoundingBox

logger = logging.getLogger("nova.screen.accessibility")


@dataclass
class WindowInfo:
    """Information about a window."""
    handle: int
    title: str
    class_name: str
    process_id: int
    process_name: str = ""
    rect: Optional[BoundingBox] = None


class WindowsAccessibility:
    """
    Windows UI Automation wrapper for read-only UI element discovery.
    
    Uses the `uiautomation` library (Windows UI Automation) to discover
    UI elements in a read-only manner.
    """

    def __init__(self):
        self._uia = None
        self._initialized = False

    def _ensure_initialized(self) -> bool:
        """Lazy initialization of UI Automation."""
        if self._initialized:
            return True

        try:
            import uiautomation as uia
            self._uia = uia
            # Set global search timeout (in milliseconds)
            uia.SetGlobalSearchTimeout(5000)
            self._initialized = True
            logger.info("Windows UI Automation initialized")
            return True
        except ImportError:
            logger.warning("uiautomation not installed - UI Automation unavailable")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize UI Automation: {e}")
            return False

    def is_available(self) -> bool:
        """Check if UI Automation is available."""
        return self._ensure_initialized()

    def get_active_window(self) -> Optional[Any]:
        """Get the currently active (foreground) window."""
        if not self._ensure_initialized():
            return None

        try:
            import uiautomation as uia
            window = uia.WindowControl(searchDepth=1)
            if window and window.Exists():
                return window
            return None
        except Exception as e:
            logger.debug(f"Failed to get active window: {e}")
            return None

    def get_window_info(self, window) -> Optional[dict]:
        """Extract information from a window element."""
        if window is None:
            return None

        try:
            import uiautomation as uia
            import psutil
            
            handle = getattr(window, "NativeWindowHandle", None)
            title = getattr(window, "Name", "") or ""
            class_name = getattr(window, "ClassName", "") or ""
            process_id = getattr(window, "ProcessId", None)
            
            # Get process name from process ID
            process_name = ""
            if process_id:
                try:
                    proc = psutil.Process(process_id)
                    process_name = proc.name()
                except Exception:
                    pass

            info = {
                "handle": handle,
                "title": title,
                "class_name": class_name,
                "process_id": process_id,
                "process_name": process_name,
            }

            # Get bounding rectangle
            try:
                rect = window.BoundingRectangle
                if rect and rect.width() > 0 and rect.height() > 0:
                    info["rect"] = (rect.left, rect.top, rect.right, rect.bottom)
            except Exception:
                pass

            return info
        except Exception as e:
            logger.debug(f"Failed to get window info: {e}")
            return None

    def get_window_elements(self, window, max_depth: int = 10) -> List[ScreenElement]:
        """
        Recursively discover UI elements in a window.
        
        Args:
            window: UIA window element
            max_depth: Maximum recursion depth to prevent infinite loops
            
        Returns:
            List of ScreenElement objects
        """
        if window is None or max_depth <= 0:
            return []

        if not self._ensure_initialized():
            return []

        elements = []

        def _walk(element, depth: int = 0):
            if depth >= max_depth:
                return

            try:
                logger.debug("[UIA DEBUG] ENTER depth=%d element=%r", depth, element)
                
                children = element.GetChildren()
                logger.debug("[UIA DEBUG] CHILDREN depth=%d count=%d", depth, len(children))
                for i, child in enumerate(children):
                    logger.debug("[UIA DEBUG] CHILD %d: type=%s", i, type(child))
                    ct = child.ControlType
                    role = self._get_control_type_name(child)
                    name = getattr(child, "Name", "") or ""
                    text = getattr(child, "Name", "") or ""
                    automation_id = getattr(child, "AutomationId", "") or ""
                    class_name = getattr(child, "ClassName", "") or ""
                    # Try to get Value pattern for editable elements
                    value = ""
                    try:
                        value_pattern = child.GetValuePattern()
                        if value_pattern:
                            value = value_pattern.Value or ""
                    except Exception:
                        pass

                    bbox = None
                    try:
                        rect = child.BoundingRectangle
                        if rect and rect.width() > 0 and rect.height() > 0:
                            bbox = (rect.left, rect.top, rect.right, rect.bottom)
                    except Exception as e:
                        logger.exception("[UIA DEBUG] BoundingRectangle failed for child %d", i)

                    enabled = True
                    try:
                        enabled = bool(getattr(child, "IsEnabled", True))
                    except Exception:
                        pass

                    try:
                        visible = bool(getattr(child, "IsOffscreen", False)) == False
                    except Exception:
                        pass

                    clickable_types = {
                        "Button", "Hyperlink", "MenuItem", "ListItem",
                        "TabItem", "TreeItem", "CheckBox", "RadioButton"
                    }
                    clickable = False
                    if hasattr(child.ControlType, "Name") and child.ControlType.Name in clickable_types:
                        clickable = True

                    try:
                        focused = bool(getattr(child, "HasKeyboardFocus", False))
                    except Exception:
                        focused = False

                    logger.debug(
                        "[UIA DEBUG] PROPERTIES role=%r name=%r text=%r automation_id=%r value=%r bbox=%r",
                        role,
                        name,
                        text,
                        automation_id,
                        value,
                        bbox,
                    )

                    # Create screen element
                    element_data = ScreenElement(
                        role=role,
                        name=name,
                        text=text,
                        automation_id=automation_id,
                        class_name=class_name,
                        bbox=bbox,
                        enabled=enabled,
                        visible=visible,
                        clickable=clickable,
                        value=value,
                        focused=focused,
                    )

                    logger.debug(
                        "[UIA DEBUG] SCREEN ELEMENT CREATED role=%r name=%r",
                        role,
                        name,
                    )

                    # DEBUG: Log filter decision
                    filter_pass = (name or text or automation_id or value or (bbox and element_data.area > 0) or role)
                    logger.debug(f"[UIA DEBUG] Filter check: name={bool(name)}, text={bool(text)}, automation_id={bool(automation_id)}, value={bool(value)}, bbox_area={bbox and element_data.area > 0}, role={bool(role)} -> KEEP={filter_pass}")

                    # Only add elements that have some useful information
                    if name or text or automation_id or value or (bbox and element_data.area > 0) or role:
                        elements.append(element_data)
                        logger.debug("[UIA DEBUG] APPENDING ELEMENT")
                    else:
                        logger.debug(f"[UIA DEBUG] DROPPED: role={role}, name={name!r}, text={text!r}, automation_id={automation_id}, bbox={bbox}, enabled={enabled}, visible={visible}, clickable={clickable}, focused={focused}")

                    logger.debug("[UIA DEBUG] APPENDED. TOTAL=%d", len(elements))

                    # Recurse into children
                    try:
                        children = element.GetChildren()
                        for child in children:
                            _walk(child, depth + 1)
                    except Exception as e:
                        logger.exception("[UIA DEBUG] Failed getting children for element %r: %s", element, e)

            except Exception as e:
                logger.exception("[UIA DEBUG] Failed processing element: %s", e)

        try:
            _walk(window)
        except Exception as e:
            logger.exception("[UIA DEBUG] Failed to walk UI tree: %s", e)

        return elements

    def _get_control_type_name(self, element) -> str:
        """Get human-readable control type name."""
        try:
            ct = getattr(element, "ControlType", None)
            if ct is None:
                return "Unknown"
            
            # ControlType can be an int or an object with Name attribute
            if isinstance(ct, int):
                # Map integer control type to name
                import uiautomation as uia
                for name in dir(uia.ControlType):
                    if not name.startswith('_'):
                        val = getattr(uia.ControlType, name)
                        if isinstance(val, int) and val == ct:
                            return name.replace('Control', '')
                return f"ControlType_{ct}"
            elif ct and hasattr(ct, "Name"):
                return ct.Name.replace('Control', '')
            return "Unknown"
        except Exception:
            return "Unknown"

    def get_foreground_window_info(self) -> Optional[dict]:
        """Get information about the foreground window."""
        window = self.get_active_window()
        return self.get_window_info(window)

    def get_active_window_elements(self, max_depth: int = 10) -> List[ScreenElement]:
        """Get all UI elements from the currently active window."""
        window = self.get_active_window()
        if window is None:
            return []
        return self.get_window_elements(window, max_depth)

    def extract_visible_text(self, elements: List[ScreenElement]) -> List[str]:
        """Extract all visible text from elements, deduplicated."""
        texts = []
        seen = set()
        for elem in elements:
            for text_attr in [elem.name, elem.text, elem.value]:
                if text_attr and text_attr.strip():
                    text_clean = text_attr.strip()
                    if text_clean not in seen and len(text_clean) > 1:
                        seen.add(text_clean)
                        texts.append(text_clean)
        return texts


# Global instance
_accessibility: Optional[WindowsAccessibility] = None


def get_accessibility() -> WindowsAccessibility:
    """Get or create the global WindowsAccessibility instance."""
    global _accessibility
    if _accessibility is None:
        _accessibility = WindowsAccessibility()
    return _accessibility


__all__ = ["WindowsAccessibility", "get_accessibility", "WindowInfo"]