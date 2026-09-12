"""
Screen capture abstraction.
Provides local-only screen capture capabilities.
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple, Any
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger("nova.screen.capture")


BoundingBox = Tuple[int, int, int, int]  # (left, top, right, bottom)


@dataclass
class ScreenCapture:
    """Container for captured screen data with metadata."""
    data: bytes
    width: int
    height: int
    format: str = "RGB"
    bbox: Optional[Tuple[int, int, int, int]] = None

    @property
    def size(self) -> Tuple[int, int]:
        return (self.width, self.height)


class ScreenCaptureBackend:
    """
    Abstract screen capture backend.
    """
    def capture(self, bbox: Optional[Tuple[int, int, int, int]] = None) -> ScreenCapture:
        raise NotImplementedError

    def capture_to_file(self, file_path: str, bbox: Optional[Tuple[int, int, int, int]] = None) -> bool:
        raise NotImplementedError


class MSSCaptureBackend:
    """Screen capture using mss (Multi-Screen Shot)."""
    
    def __init__(self):
        self._mss = None
        self._monitor = None

    def _ensure_initialized(self) -> bool:
        if self._mss is not None:
            return True
        try:
            import mss
            self._mss = mss.mss()
            # Use the primary monitor by default
            self._monitor = self._mss.monitors[1] if len(self._mss.monitors) > 1 else self._mss.monitors[0]
            return True
        except ImportError:
            logger.warning("mss not installed - screen capture unavailable")
            return False
        except Exception as e:
            logger.error(f"Failed to initialize MSS: {e}")
            return False

    def capture(self, bbox: Optional[Tuple[int, int, int, int]] = None) -> ScreenCapture:
        if not self._ensure_initialized():
            raise RuntimeError("MSS not available")

        if bbox:
            left, top, right, bottom = bbox
            monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
        else:
            monitor = self._monitor

        screenshot = self._mss.grab(monitor)
        # Return ScreenCapture with metadata
        return ScreenCapture(
            data=screenshot.rgb,
            width=monitor["width"],
            height=monitor["height"],
            format="RGB",
            bbox=bbox
        )

    def capture_to_file(self, file_path: str, bbox: Optional[Tuple[int, int, int, int]] = None) -> bool:
        try:
            import mss.tools
            if bbox:
                left, top, right, bottom = bbox
                monitor = {"left": left, "top": top, "width": right - left, "height": bottom - top}
            else:
                monitor = self._monitor

            screenshot = self._mss.grab(monitor)
            mss.tools.to_png(screenshot.rgb, screenshot.size, output=file_path)
            return True
        except Exception as e:
            logger.error(f"Failed to save screenshot: {e}")
            return False


# Capture backends

class PillowCaptureBackend:
    """Screen capture using Pillow's ImageGrab (Windows only)."""

    def __init__(self):
        self._initialized = None

    def _ensure_initialized(self) -> bool:
        if self._initialized is not None:
            return self._initialized
        try:
            from PIL import ImageGrab  # noqa: F401
            self._initialized = True
            return True
        except Exception:
            logger.warning("Pillow ImageGrab not available - screen capture unavailable")
            self._initialized = False
            return False

    def capture(self, bbox: Optional[Tuple[int, int, int, int]] = None) -> ScreenCapture:
        if not self._ensure_initialized():
            raise RuntimeError("Pillow ImageGrab not available")
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=bbox) if bbox else ImageGrab.grab()
        img = img.convert("RGB")
        data = img.tobytes()
        width, height = img.size
        return ScreenCapture(data=data, width=width, height=height, format="RGB", bbox=bbox)

    def capture_to_file(self, file_path: str, bbox: Optional[Tuple[int, int, int, int]] = None) -> bool:
        if not self._ensure_initialized():
            return False
        from PIL import ImageGrab
        img = ImageGrab.grab(bbox=bbox) if bbox else ImageGrab.grab()
        try:
            img.save(file_path)
            return True
        except Exception as e:
            logger.error(f"Failed to save screenshot via Pillow: {e}")
            return False

# Only MSS backend for Phase 1
_capture_backend = None


def get_capture_backend():
    """Get or create a screen capture backend.
    Preference order: Pillow ImageGrab (native) -> MSS.
    Returns None if no backend is available."""
    global _capture_backend
    if _capture_backend is None:
        # Try Pillow first
        pillow_backend = PillowCaptureBackend()
        if pillow_backend._ensure_initialized():
            _capture_backend = pillow_backend
        else:
            # Fallback to MSS if Pillow not available
            mss_backend = MSSCaptureBackend()
            if mss_backend._ensure_initialized():
                _capture_backend = mss_backend
            else:
                return None
    return _capture_backend


def capture_screen(bbox: Optional[Tuple[int, int, int, int]] = None):
    """
    Capture the screen (or a region) and return a ScreenCapture with metadata.
    
    Args:
        bbox: Optional bounding box (left, top, right, bottom)
        
    Returns:
        ScreenCapture object with data and metadata
    """
    backend = get_capture_backend()
    if backend is None:
        raise RuntimeError("No screen capture backend available (install mss)")
    return backend.capture(bbox)


def capture_screen_to_file(file_path: str, bbox: Optional[Tuple[int, int, int, int]] = None) -> bool:
    """
    Capture the screen (or a region) and save to file.
    
    Args:
        file_path: Output file path
        bbox: Optional bounding box (left, top, right, bottom)
        
    Returns:
        True if successful
    """
    backend = get_capture_backend()
    if backend is None:
        return False
    return backend.capture_to_file(file_path, bbox)


def get_screen_size() -> Tuple[int, int]:
    """Get the primary screen resolution."""
    try:
        import mss
        with mss.mss() as sct:
            monitor = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
            return (monitor["width"], monitor["height"])
    except Exception:
        return (1920, 1080)  # fallback


__all__ = [
    "ScreenCapture",
    "capture_screen",
    "capture_screen_to_file",
    "get_screen_size",
]