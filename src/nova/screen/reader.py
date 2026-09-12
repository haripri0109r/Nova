"""
Screen Reader - combines UI Automation and OCR for comprehensive screen reading.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional, Tuple, Set, Dict
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from .elements import ScreenElement, ScreenContext, BoundingBox
from .accessibility import WindowsAccessibility, get_accessibility
from .capture import capture_screen, ScreenCapture
from .ocr import get_ocr, OfflineOCR

logger = logging.getLogger("nova.screen.reader")


@dataclass
class ScreenReadingResult:
    """Result of screen reading operation."""
    context: "ScreenContext"
    ocr_used: bool = False
    ocr_regions: List[Tuple[int, int, int, int]] = field(default_factory=list)
    uia_elements_found: int = 0
    ocr_text_added: int = 0


@dataclass
class TextSource:
    """Source of extracted text for debugging/merging."""
    text: str
    source: str  # "uia" or "ocr"
    bbox: Optional[Tuple[int, int, int, int]] = None
    confidence: float = 1.0


class ScreenReader:
    """
    High-level screen reader combining UI Automation and OCR.
    
    Primary strategy: Use UI Automation first, then fall back to OCR
    for regions where UIA provides insufficient text information.
    """
    
    def __init__(
        self,
        accessibility = None,
        ocr: Optional["OfflineOCR"] = None,
        max_elements: int = 200,
        max_depth: int = 10,
        enable_ocr_fallback: bool = True,
        ocr_confidence_threshold: float = 0.3,
        uia_sufficiency_threshold: int = 50,  # Minimum characters for UIA to be considered sufficient
    ):
        """
        Initialize the screen reader.
        
        Args:
            accessibility: WindowsAccessibility instance (creates default if None)
            ocr: OfflineOCR instance (creates default if None)
            max_elements: Maximum elements to include in context
            max_depth: Maximum UI tree depth
            enable_ocr_fallback: Whether to use OCR as fallback
            ocr_confidence_threshold: Minimum confidence for OCR text
            uia_sufficiency_threshold: Minimum characters for UIA to be considered sufficient
        """
        from .accessibility import get_accessibility
        from .ocr import get_ocr
        
        self.accessibility = accessibility or get_accessibility()
        self.ocr = ocr or get_ocr()
        self.max_elements = max_elements
        self.max_depth = max_depth
        self.enable_ocr_fallback = enable_ocr_fallback
        self.ocr_confidence_threshold = ocr_confidence_threshold
        self.uia_sufficiency_threshold = uia_sufficiency_threshold
    
    def _is_uia_sufficient(self, context: "ScreenContext") -> bool:
        """
        Determine if UIA text is sufficient to skip OCR.
        
        Heuristic: UIA is sufficient if:
        - There is meaningful visible text
        - Text is not just window chrome/title bar
        - Total text length exceeds threshold
        """
        if not context.visible_text:
            return False
        
        total_text = " ".join(context.visible_text)
        text_length = len(total_text.strip())
        
        # Check if we have meaningful content (not just window chrome)
        if text_length < self.uia_sufficiency_threshold:
            return False
        
        # Check if we have actual content vs just window chrome
        chrome_text = {"minimize", "maximize", "close", "restore", "settings", "help", "file", "edit", "view", "window"}
        meaningful_text = [t for t in context.visible_text 
                          if t.lower().strip() not in chrome_text and len(t.strip()) > 2]
        
        if len(" ".join(meaningful_text).strip()) < self.uia_sufficiency_threshold:
            return False
        
        return True
    
    def _should_use_ocr(self, context: "ScreenContext") -> bool:
        """Determine if OCR fallback should be used."""
        if not self.enable_ocr_fallback:
            return False
        
        from .ocr import get_ocr
        ocr = get_ocr()
        if not ocr.is_available():
            return False
        
        # Check if UIA text is sufficient
        if self._is_uia_sufficient(context):
            return False
        
        return True
    
    def _apply_ocr_fallback(self, context: "ScreenContext") -> Dict:
        """Apply OCR to regions where UIA text is missing."""
        from .capture import capture_screen
        from .ocr import get_ocr
        
        # Capture screen
        try:
            screen_capture = capture_screen()
        except Exception as e:
            logger.warning(f"Screen capture failed for OCR: {e}")
            return {"regions": [], "text_added": 0, "ocr_texts": []}
        
        # Get OCR instance
        ocr = get_ocr()
        if not ocr.is_available():
            return {"regions": [], "text_added": 0, "ocr_texts": []}
        
        # Get OCR text from full screen
        try:
            ocr_texts = self.ocr.read(
                screen_capture.data, 
                screen_capture.width, 
                screen_capture.height
            )
        except Exception as e:
            logger.warning(f"OCR read failed: {e}")
            return {"regions": [], "text_added": 0, "ocr_texts": []}
        
        if not ocr_texts:
            return {"regions": [], "text_added": 0, "ocr_texts": []}
        
        return {
            "regions": [(0, 0, 0, 0)],  # Full screen
            "text_added": len(ocr_texts),
            "ocr_texts": ocr_texts
        }
    
    def _merge_texts(self, uia_texts: List[str], ocr_texts: List[str]) -> List[str]:
        """Merge UIA and OCR texts with deduplication."""
        # Normalize texts for comparison
        def normalize(text: str) -> str:
            return re.sub(r'\s+', ' ', text.strip().lower())
        
        uia_normalized = {normalize(t): t for t in uia_texts if t.strip()}
        ocr_normalized = {normalize(t): t for t in ocr_texts if t.strip()}
        
        # Start with UIA texts (higher priority)
        merged = list(uia_texts)
        
        # Add OCR texts that aren't already present
        for norm_text, orig_text in ocr_normalized.items():
            if norm_text not in uia_normalized:
                # Check similarity with existing texts
                is_duplicate = False
                for existing_norm in uia_normalized:
                    if SequenceMatcher(None, norm_text, existing_norm).ratio() > 0.85:
                        is_duplicate = True
                        break
                if not is_duplicate:
                    # Find best match to preserve original casing from OCR
                    merged.append(ocr_texts[list(ocr_normalized.keys()).index(norm_text)])
        
        return merged
    
    def read_active_screen(self) -> "ScreenContext":
        """Read the currently active screen and return unified context."""
        from .elements import ScreenContext
        from .context import ScreenContextBuilder
        from .accessibility import get_accessibility
        from .ocr import get_ocr
        
        # Use existing context builder for UIA data
        builder = ScreenContextBuilder(
            accessibility=get_accessibility(),
            max_elements=self.max_elements,
            max_depth=self.max_depth
        )
        context = builder.build()
        
        # If UIA failed completely, return empty context
        if not context.elements and not context.visible_text:
            return context
        
        # Check if OCR fallback is needed
        ocr_used = False
        ocr_texts = []
        
        if self._should_use_ocr(context):
            ocr_result = self._apply_ocr_fallback(context)
            if ocr_result and ocr_result.get("ocr_texts"):
                ocr_texts = ocr_result["ocr_texts"]
                # Merge OCR texts with UIA texts
                context.visible_text = self._merge_texts(context.visible_text, ocr_texts)
                ocr_used = True
        
        # Mark OCR usage on context for prompt generation
        context._last_ocr_used = ocr_used
        
        return context
    
    def to_prompt_text(self, context: "ScreenContext") -> str:
        """Generate compact text representation for LLM consumption."""
        lines = []
        
        if context.application:
            lines.append(f"Application: {context.application}")
        if context.window_title:
            lines.append(f"Window: {context.window_title}")
        
        if context.visible_text:
            lines.append("\nVisible text:")
            for text in context.visible_text[:20]:  # Limit to 20 items
                lines.append(f"  {text}")
        
        if context.elements:
            interactive = [e for e in context.elements if e.clickable]
            if interactive:
                lines.append("\nInteractive elements:")
                for elem in interactive[:10]:  # Limit to 10
                    state = "focused" if elem.focused else ""
                    lines.append(f"  [{elem.role}] {elem.name} {state}")
        
        if context.active_element:
            lines.append(f"\nFocused: {context.active_element.name} ({context.active_element.role})")
        
        return "\n".join(lines)


__all__ = ["ScreenReader", "ScreenReadingResult", "TextSource"]