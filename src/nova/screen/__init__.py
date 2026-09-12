"""
Nova Screen Package - Offline screen understanding for Windows.
"""
from .elements import ScreenElement, ScreenContext
from .context import ScreenContextBuilder
from .accessibility import WindowsAccessibility, get_accessibility
from .capture import capture_screen, capture_screen_to_file, get_screen_size, ScreenCapture
from .ocr import OfflineOCR, TesseractOCR, get_ocr
from .reader import ScreenReader

__all__ = [
    "ScreenElement",
    "ScreenContext",
    "ScreenContextBuilder",
    "WindowsAccessibility",
    "get_accessibility",
    "capture_screen",
    "capture_screen_to_file",
    "get_screen_size",
    "ScreenCapture",
    "OfflineOCR",
    "TesseractOCR",
    "get_ocr",
    "ScreenReader",
]