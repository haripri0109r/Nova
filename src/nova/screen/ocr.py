"""
Offline OCR abstraction for Nova.
Provides text extraction from images using local OCR engines.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Any
from pathlib import Path

from .capture import ScreenCapture
from .elements import BoundingBox

logger = logging.getLogger("nova.screen.ocr")


@dataclass
class OCRResult:
    """Result of OCR text extraction."""
    text: str
    confidence: float
    bbox: Optional[BoundingBox] = None
    language: str = "en"


class OCRBackend(ABC):
    """Abstract base class for OCR backends."""
    
    @abstractmethod
    def is_available(self) -> bool:
        """Check if the OCR backend is available."""
        pass
    
    @abstractmethod
    def read(self, image_data: bytes, width: int, height: int, 
             bbox: Optional[BoundingBox] = None) -> List[str]:
        """Extract text from image data.
        
        Args:
            image_data: Raw image bytes (RGB format)
            width: Image width in pixels
            height: Image height in pixels
            bbox: Optional bounding box to restrict OCR region
            
        Returns:
            List of recognized text strings
        """
        pass
    
    @abstractmethod
    def read_with_details(self, image_data: bytes, width: int, height: int,
                          bbox: Optional[BoundingBox] = None) -> List[Tuple[str, float, BoundingBox]]:
        """Extract text with confidence and bounding boxes.
        
        Returns:
            List of (text, confidence, bbox) tuples
        """
        pass


class TesseractOCR:
    """Tesseract OCR backend using pytesseract."""
    
    def __init__(self, language: str = "eng", tesseract_cmd: Optional[str] = None):
        self._language = language
        self._tesseract_cmd = tesseract_cmd
        self._tesseract = None
        self._available = False
    
    def is_available(self) -> bool:
        if self._available:
            return True
        try:
            import pytesseract
            # Check if tesseract binary is actually available
            tesseract_path = self._tesseract_cmd or shutil.which("tesseract")
            if not tesseract_path:
                logger.warning("Tesseract binary not found in PATH")
                return False
            # Verify it works by checking version
            try:
                result = subprocess.run([tesseract_path, "--version"], capture_output=True, timeout=5)
                if result.returncode != 0:
                    logger.warning(f"Tesseract binary check failed: {result.stderr.decode()}")
                    return False
            except Exception as e:
                logger.warning(f"Tesseract binary execution failed: {e}")
                return False
            if self._tesseract_cmd:
                import pytesseract as pt
                pt.pytesseract.tesseract_cmd = self._tesseract_cmd
            self._available = True
            return True
        except ImportError:
            logger.warning("pytesseract not installed - Tesseract OCR unavailable")
            return False
        except Exception as e:
            logger.warning(f"Tesseract OCR unavailable: {e}")
            return False
    
    def read(self, image_data: bytes, width: int, height: int,
             bbox: Optional[BoundingBox] = None) -> List[str]:
        """Extract text from image data."""
        if not self.is_available():
            return []
        
        try:
            import pytesseract
            from PIL import Image
            import io
            
            # Create PIL image from raw bytes
            image = Image.frombytes("RGB", (width, height), image_data)
            
            # Crop to bbox if provided
            if bbox:
                left, top, right, bottom = bbox
                image = image.crop((left, top, right, bottom))
            
            # Extract text
            text = pytesseract.image_to_string(image, lang="eng")
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            return [line for line in lines if len(line) > 1]
        except Exception as e:
            logger.warning(f"Tesseract OCR failed: {e}")
            return []
    
    def read_with_details(self, image_data: bytes, width: int, height: int,
                          bbox: Optional[BoundingBox] = None) -> List[Tuple[str, float, BoundingBox]]:
        """Extract text with confidence and bounding boxes."""
        if not self.is_available():
            return []
        
        try:
            import pytesseract
            from PIL import Image
            
            image = Image.frombytes("RGB", (width, height), image_data)
            
            if bbox:
                left, top, right, bottom = bbox
                image = image.crop((left, top, right, bottom))
                offset_x, offset_y = left, top
            else:
                offset_x, offset_y = 0, 0
            
            # Get detailed OCR data
            data = pytesseract.image_to_data(image, output_type='data.frame')
            
            results = []
            for _, row in data.iterrows():
                text = str(row.get('text', '')).strip()
                conf = float(row.get('conf', 0))
                if text and conf > 30:  # Minimum confidence threshold
                    x = int(row.get('left', 0)) + (bbox[0] if bbox else 0)
                    y = int(row.get('top', 0)) + (bbox[1] if bbox else 0)
                    w = int(row.get('width', 0))
                    h = int(row.get('height', 0))
                    if w > 0 and h > 0:
                        bbox_result = (x, y, x + w, y + h)
                        results.append((text, conf / 100.0, bbox_result))
            
            return results
        except Exception as e:
            logger.warning(f"Tesseract OCR detail failed: {e}")
            return []


class EasyOCR:
    """EasyOCR backend (optional, heavier but supports more languages)."""
    
    def __init__(self, languages: List[str] = None):
        self._languages = languages or ["en"]
        self._reader = None
        self._available = False
    
    def is_available(self) -> bool:
        if self._available:
            return True
        try:
            import easyocr
            self._reader = easyocr.Reader(self._languages, gpu=False)
            self._available = True
            return True
        except ImportError:
            logger.warning("easyocr not installed - EasyOCR unavailable")
            return False
        except Exception as e:
            logger.warning(f"EasyOCR unavailable: {e}")
            return False
    
    def read(self, image_data: bytes, width: int, height: int,
             bbox: Optional[BoundingBox] = None) -> List[str]:
        if not self.is_available():
            return []
        
        try:
            import numpy as np
            from PIL import Image
            
            image = Image.frombytes("RGB", (width, height), image_data)
            
            if bbox:
                left, top, right, bottom = bbox
                image = image.crop((left, top, right, bottom))
            
            # Convert to numpy array for easyocr
            img_np = np.array(image)
            results = self._reader.readtext(img_np)
            
            texts = []
            for (bbox_coords, text, conf) in results:
                if conf > 0.3 and text.strip():
                    texts.append(text.strip())
            return texts
        except Exception as e:
            logger.warning(f"EasyOCR failed: {e}")
            return []
    
    def read_with_details(self, image_data: bytes, width: int, height: int,
                          bbox: Optional[BoundingBox] = None) -> List[Tuple[str, float, BoundingBox]]:
        if not self.is_available():
            return []
        
        try:
            import numpy as np
            from PIL import Image
            
            image = Image.frombytes("RGB", (width, height), image_data)
            
            if bbox:
                left, top, right, bottom = bbox
                image = image.crop((left, top, right, bottom))
                offset_x, offset_y = left, top
            else:
                offset_x, offset_y = 0, 0
            
            img_np = np.array(image)
            results = self._reader.readtext(img_np)
            
            results_list = []
            for (bbox_coords, text, conf) in results:
                if conf > 0.3 and text.strip():
                    # Convert bbox_coords to our format
                    xs = [p[0] for p in bbox_coords]
                    ys = [p[1] for p in bbox_coords]
                    x_min, x_max = min(xs), max(xs)
                    y_min, y_max = min(ys), max(ys)
                    bbox_result = (x_min + (bbox[0] if bbox else 0), 
                                  y_min + (bbox[1] if bbox else 0),
                                  x_max + (bbox[0] if bbox else 0), 
                                  y_max + (bbox[1] if bbox else 0))
                    results.append((text.strip(), conf, bbox_result))
            
            return results
        except Exception as e:
            logger.warning(f"EasyOCR detail failed: {e}")
            return []


class WindowsOCR:
    """Windows native OCR backend using Windows.Media.Ocr (winsdk).
    
    Fully offline, no external dependencies, uses Windows built-in OCR engine.
    Requires Windows 10+ and winsdk package.
    """
    
    def __init__(self, language: str = "en-US"):
        self._language = language
        self._engine = None
        self._available = False
    
    def is_available(self) -> bool:
        if self._available:
            return True
        try:
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.globalization import Language
            
            # Try to create engine for specified language
            lang = Language(self._language)
            engine = OcrEngine.try_create_from_language(lang)
            if engine is None:
                # Fallback to user profile languages
                engine = OcrEngine.try_create_from_user_profile_languages()
                if engine is None:
                    logger.warning(f"Windows OCR engine not available for language: {self._language}")
                    return False
            
            self._engine = engine
            self._available = True
            logger.info(f"Windows OCR backend initialized (language: {engine.recognizer_language.display_name})")
            return True
        except ImportError:
            logger.warning("winsdk not installed - Windows OCR unavailable")
            return False
        except Exception as e:
            logger.warning(f"Windows OCR unavailable: {e}")
            return False
    
    def _create_software_bitmap(self, image_data: bytes, width: int, height: int):
        """Convert RGB bytes to SoftwareBitmap for Windows OCR."""
        import numpy as np
        from winsdk.windows.graphics.imaging import SoftwareBitmap, BitmapPixelFormat, BitmapAlphaMode, BitmapDecoder
        from winsdk.windows.storage.streams import InMemoryRandomAccessStream, DataWriter
        from PIL import Image
        import io
        
        # Convert RGB bytes to PIL Image
        rgb_array = np.frombuffer(image_data, dtype=np.uint8).reshape(height, width, 3)
        img = Image.fromarray(rgb_array, "RGB")
        
        # Save as PNG to in-memory stream
        stream = InMemoryRandomAccessStream()
        output_stream = stream.get_output_stream_at(0)
        writer = DataWriter(output_stream)
        
        png_bytes = io.BytesIO()
        img.save(png_bytes, "PNG")
        png_data = png_bytes.getvalue()
        
        writer.write_bytes(png_data)
        writer.store_async().get_results()
        output_stream.flush_async().get_results()
        
        # Seek to beginning for decoder
        stream.seek(0)
        
        return stream
    
    async def _recognize_async(self, image_data: bytes, width: int, height: int):
        """Run OCR recognition asynchronously."""
        from winsdk.windows.graphics.imaging import BitmapDecoder, SoftwareBitmap, BitmapPixelFormat
        
        stream = self._create_software_bitmap(image_data, width, height)
        decoder = await BitmapDecoder.create_async(stream)
        software_bitmap = await decoder.get_software_bitmap_async()
        
        # Convert to BGRA8 if needed (Windows OCR prefers BGRA8)
        if software_bitmap.bitmap_pixel_format != BitmapPixelFormat.BGRA8:
            software_bitmap = SoftwareBitmap.convert(software_bitmap, BitmapPixelFormat.BGRA8)
        
        result = await self._engine.recognize_async(software_bitmap)
        return result
    
    def read(self, image_data: bytes, width: int, height: int,
             bbox: Optional[BoundingBox] = None) -> List[str]:
        """Extract text from image data."""
        if not self.is_available():
            return []
        
        # Handle bbox by cropping image first
        if bbox:
            left, top, right, bottom = bbox
            # Crop the image data
            import numpy as np
            from PIL import Image
            rgb_array = np.frombuffer(image_data, dtype=np.uint8).reshape(height, width, 3)
            cropped = rgb_array[top:bottom, left:right]
            image_data = cropped.tobytes()
            width = right - left
            height = bottom - top
        
        try:
            import asyncio
            result = asyncio.run(self._recognize_async(image_data, width, height))
            if result and result.text:
                lines = [line.text.strip() for line in result.lines if line.text.strip()]
                return [line for line in lines if len(line) > 1]
            return []
        except Exception as e:
            logger.warning(f"Windows OCR failed: {e}")
            return []
    
    def read_with_details(self, image_data: bytes, width: int, height: int,
                          bbox: Optional[BoundingBox] = None) -> List[Tuple[str, float, BoundingBox]]:
        """Extract text with confidence and bounding boxes."""
        if not self.is_available():
            return []
        
        # Handle bbox by cropping image first
        offset_x, offset_y = 0, 0
        if bbox:
            left, top, right, bottom = bbox
            offset_x, offset_y = left, top
            import numpy as np
            from PIL import Image
            rgb_array = np.frombuffer(image_data, dtype=np.uint8).reshape(height, width, 3)
            cropped = rgb_array[top:bottom, left:right]
            image_data = cropped.tobytes()
            width = right - left
            height = bottom - top
        
        try:
            import asyncio
            result = asyncio.run(self._recognize_async(image_data, width, height))
            if not result or not result.lines:
                return []
            
            results = []
            for line in result.lines:
                text = line.text.strip()
                if not text or len(text) <= 1:
                    continue
                # Windows OCR doesn't provide confidence scores directly
                # Use a default high confidence for recognized text
                # Bounding box from line's bounding_rect (in logical pixels)
                rect = line.bounding_rect
                if rect:
                    x = int(rect.x) + offset_x
                    y = int(rect.y) + offset_y
                    w = int(rect.width)
                    h = int(rect.height)
                    if w > 0 and h > 0:
                        bbox_result = (x, y, x + w, y + h)
                        results.append((text, 0.9, bbox_result))
            
            return results
        except Exception as e:
            logger.warning(f"Windows OCR detail failed: {e}")
            return []


class OfflineOCR:
    """High-level offline OCR interface that tries available backends."""
    
    def __init__(self, preferred_backend: str = "tesseract"):
        self._backends = []
        self._preferred = preferred_backend
        self._initialized = False
        self._primary = None
        self._fallback = None
    
    def _initialize_backends(self):
        """Initialize available OCR backends in order of preference.
        
        Priority:
        1. Windows Native OCR (winsdk) - fully offline, no external deps, Windows built-in
        2. Tesseract OCR - lightweight, good for English, requires tesseract binary
        3. EasyOCR - heavier but supports more languages, optional
        
        Fallbacks are initialized lazily only when primary fails.
        """
        if self._initialized:
            return
        
        # Try Windows Native OCR first (highest priority - fully offline, native)
        try:
            windows_ocr = WindowsOCR()
            if windows_ocr.is_available():
                self._backends.append(windows_ocr)
                self._primary = windows_ocr
                logger.info("Windows Native OCR backend initialized (primary)")
        except Exception as e:
            logger.warning(f"Windows OCR initialization failed: {e}")
        
        # If Windows OCR works, we're done - fallbacks initialized lazily
        if self._primary:
            self._initialized = True
            logger.info("Primary OCR available, fallbacks will be initialized lazily if needed")
            return
        
        # Try Tesseract as fallback (only if no primary)
        try:
            tesseract = TesseractOCR()
            if tesseract.is_available():
                self._backends.append(tesseract)
                self._primary = tesseract
                logger.info("Tesseract OCR backend initialized (primary)")
        except Exception as e:
            logger.warning(f"Tesseract OCR initialization failed: {e}")
        
        # Try EasyOCR as last resort (only if no primary)
        if not self._primary:
            try:
                easyocr_backend = EasyOCR(["en"])
                if easyocr_backend.is_available():
                    self._backends.append(easyocr_backend)
                    self._primary = easyocr_backend
                    logger.info("EasyOCR backend initialized (primary)")
            except Exception:
                pass
        
        self._initialized = True
        if not self._backends:
            logger.warning("No OCR backends available")
    
    def _ensure_fallbacks_initialized(self):
        """Lazily initialize fallback backends if primary exists but fallbacks don't."""
        if self._fallback is not None or self._primary is None:
            return
        
        # Try Tesseract as fallback
        try:
            tesseract = TesseractOCR()
            if tesseract.is_available():
                self._backends.append(tesseract)
                self._fallback = tesseract
                logger.info("Tesseract OCR backend initialized (fallback)")
        except Exception as e:
            logger.warning(f"Tesseract OCR fallback initialization failed: {e}")
        
        # Try EasyOCR as last resort
        if self._fallback is None:
            try:
                easyocr_backend = EasyOCR(["en"])
                if easyocr_backend.is_available():
                    self._backends.append(easyocr_backend)
                    self._fallback = easyocr_backend
                    logger.info("EasyOCR backend initialized (fallback)")
            except Exception:
                pass
    
    def is_available(self) -> bool:
        """Check if any OCR backend is available."""
        if not self._initialized:
            self._initialize_backends()
        return len(self._backends) > 0
    
    def read(self, image_data: bytes, width: int, height: int,
             bbox: Optional[BoundingBox] = None) -> List[str]:
        """Extract text from image using available backends."""
        if not self.is_available():
            return []
        
        # Try primary backend
        if self._primary:
            try:
                result = self._primary.read(image_data, width, height, bbox)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Primary OCR backend failed: {e}")
        
        # Initialize fallbacks lazily if primary failed
        self._ensure_fallbacks_initialized()
        
        # Try fallback
        if self._fallback:
            try:
                result = self._fallback.read(image_data, width, height, bbox)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Fallback OCR backend failed: {e}")
        
        return []
    
    def read_with_details(self, image_data: bytes, width: int, height: int,
                          bbox: Optional[BoundingBox] = None) -> List[Tuple[str, float, BoundingBox]]:
        """Extract text with confidence and bounding boxes."""
        if not self.is_available():
            return []
        
        if self._primary:
            try:
                result = self._primary.read_with_details(image_data, width, height, bbox)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Primary OCR detail failed: {e}")
        
        # Initialize fallbacks lazily if primary failed
        self._ensure_fallbacks_initialized()
        
        if self._fallback:
            try:
                result = self._fallback.read_with_details(image_data, width, height, bbox)
                if result:
                    return result
            except Exception as e:
                logger.warning(f"Fallback OCR detail failed: {e}")
        
        return []
    
    def is_available_sync(self) -> bool:
        """Synchronous availability check (for quick checks)."""
        # Check Windows OCR first (fastest)
        try:
            from winsdk.windows.media.ocr import OcrEngine
            from winsdk.windows.globalization import Language
            engine = OcrEngine.try_create_from_language(Language("en-US"))
            if engine:
                return True
        except Exception:
            pass
        # Check Tesseract
        try:
            import pytesseract
            tesseract_path = shutil.which("tesseract")
            if tesseract_path:
                return True
        except Exception:
            pass
        # Check EasyOCR
        try:
            import easyocr
            return True
        except ImportError:
            return False


# Global OCR instance
_ocr_instance: Optional[OfflineOCR] = None


def get_ocr() -> OfflineOCR:
    """Get or create the global OCR instance."""
    global _ocr_instance
    if _ocr_instance is None:
        _ocr_instance = OfflineOCR()
    return _ocr_instance


__all__ = [
    "OfflineOCR",
    "TesseractOCR",
    "EasyOCR",
    "WindowsOCR",
    "OCRResult",
    "get_ocr",
]
