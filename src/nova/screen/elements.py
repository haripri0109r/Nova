"""
Screen element and context data models.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List, Tuple


BoundingBox = Tuple[int, int, int, int]  # (left, top, right, bottom)


@dataclass
class ScreenElement:
    """
    Represents a UI element discovered through Windows UI Automation.
    """
    role: str = ""
    name: str = ""
    text: str = ""
    automation_id: str = ""
    class_name: str = ""
    bbox: Optional[Tuple[int, int, int, int]] = None
    enabled: bool = True
    visible: bool = True
    clickable: bool = False
    value: Optional[str] = None
    focused: bool = False

    def __post_init__(self):
        # Ensure bbox is a tuple if provided as list
        if self.bbox is not None and not isinstance(self.bbox, tuple):
            self.bbox = tuple(self.bbox)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "role": self.role,
            "name": self.name,
            "text": self.text,
            "automation_id": self.automation_id,
            "class_name": self.class_name,
            "bbox": self.bbox,
            "enabled": self.enabled,
            "visible": self.visible,
            "clickable": self.clickable,
            "value": self.value,
            "focused": self.focused,
        }

    @property
    def center(self) -> Optional[Tuple[int, int]]:
        """Return the center point of the element's bounding box."""
        if self.bbox is None:
            return None
        left, top, right, bottom = self.bbox
        return ((left + right) // 2, (top + bottom) // 2)

    @property
    def area(self) -> int:
        """Return the area of the element's bounding box."""
        if self.bbox is None:
            return 0
        left, top, right, bottom = self.bbox
        return max(0, right - left) * max(0, bottom - top)


@dataclass
class ScreenContext:
    """
    Aggregated screen context built from UI Automation data.
    """
    application: str = ""
    window_title: str = ""
    active_element: Optional[ScreenElement] = None
    elements: List[ScreenElement] = field(default_factory=list)
    visible_text: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "application": self.application,
            "window_title": self.window_title,
            "active_element": self.active_element.to_dict() if self.active_element else None,
            "elements": [e.to_dict() for e in self.elements],
            "visible_text": self.visible_text,
        }

    def get_elements_by_role(self, role: str) -> List[ScreenElement]:
        """Filter elements by role."""
        return [e for e in self.elements if e.role.lower() == role.lower()]

    def get_clickable_elements(self) -> List[ScreenElement]:
        """Return all clickable elements."""
        return [e for e in self.elements if e.clickable]

    def find_element_by_name(self, name: str) -> Optional[ScreenElement]:
        """Find an element by name (case-insensitive)."""
        name_lower = name.lower()
        for elem in self.elements:
            if name_lower in elem.name.lower() or name_lower in elem.text.lower():
                return elem
        return None

    def get_text_content(self) -> str:
        """Get all visible text as a single string."""
        return "\n".join(self.visible_text)

    def to_prompt_text(self) -> str:
        """Generate compact text representation for LLM consumption."""
        lines = []
        
        if self.application:
            lines.append(f"Application: {self.application}")
        if self.window_title:
            lines.append(f"Window: {self.window_title}")
        
        if self.visible_text:
            lines.append("\nVisible text:")
            for text in self.visible_text[:20]:  # Limit to 20 items
                lines.append(f"  {text}")
        
        if self.elements:
            interactive = [e for e in self.elements if e.clickable]
            if interactive:
                lines.append("\nInteractive elements:")
                for elem in interactive[:10]:  # Limit to 10 items
                    state = "focused" if elem.focused else ""
                    lines.append(f"  [{elem.role}] {elem.name} {state}")
        
        if self.active_element:
            lines.append(f"\nFocused: {self.active_element.name} ({self.active_element.role})")
        
        lines.append(f"\nOCR used: {'YES' if hasattr(self, '_last_ocr_used') and self._last_ocr_used else 'NO'}")
        
        return "\n".join(lines)


__all__ = ["ScreenElement", "ScreenContext"]