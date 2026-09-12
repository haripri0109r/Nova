"""
Unit tests for OCR backends.
"""
import pytest
import sys
sys.path.insert(0, 'src')

from unittest.mock import Mock, patch, MagicMock, AsyncMock
from nova.screen.ocr import WindowsOCR, TesseractOCR, OfflineOCR, EasyOCR
from nova.screen.elements import BoundingBox


class TestTesseractOCR:
    """Tests for TesseractOCR class."""

    def test_is_available_false_when_binary_missing(self):
        """Test is_available returns False when tesseract binary not in PATH."""
        with patch('shutil.which', return_value=None):
            ocr = TesseractOCR()
            assert ocr.is_available() is False

    def test_is_available_false_when_pytesseract_not_installed(self):
        """Test is_available returns False when pytesseract not installed."""
        with patch('shutil.which', return_value='/usr/bin/tesseract'):
            with patch.dict('sys.modules', {'pytesseract': None}):
                ocr = TesseractOCR()
                assert ocr.is_available() is False

    def test_is_available_true_when_binary_exists(self):
        """Test is_available returns True when tesseract binary exists."""
        with patch('shutil.which', return_value='/usr/bin/tesseract'):
            with patch('subprocess.run') as mock_run:
                mock_run.return_value.returncode = 0
                mock_run.return_value.stdout = b'tesseract 5.0.0'
                mock_run.return_value.stderr = b''
                
                # Mock pytesseract import
                with patch.dict('sys.modules', {'pytesseract': Mock()}):
                    ocr = TesseractOCR()
                    assert ocr.is_available() is True

    def test_read_returns_empty_when_unavailable(self):
        """Test read returns empty list when OCR unavailable."""
        ocr = TesseractOCR()
        ocr._available = False
        result = ocr.read(b'', 100, 100)
        assert result == []


class TestWindowsOCR:
    """Tests for WindowsOCR class."""

    def test_is_available_false_when_winsdk_not_installed(self):
        """Test is_available returns False when winsdk not installed."""
        with patch.dict('sys.modules', {'winsdk': None}):
            ocr = WindowsOCR()
            assert ocr.is_available() is False

    def test_is_available_true_when_winsdk_available(self):
        """Test is_available returns True when winsdk and OCR engine available."""
        mock_engine = Mock()
        mock_engine.recognizer_language.display_name = "English (United States)"
        
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': Mock(OcrEngine=Mock(
                try_create_from_language=Mock(return_value=mock_engine),
                try_create_from_user_profile_languages=Mock(return_value=None)
            )),
            'winsdk.windows.globalization': Mock(Language=Mock())
        }):
            ocr = WindowsOCR()
            assert ocr.is_available() is True
            assert ocr._engine == mock_engine

    def test_is_available_fallback_to_user_profile(self):
        """Test is_available falls back to user profile languages."""
        mock_engine = Mock()
        mock_engine.recognizer_language.display_name = "English (United States)"
        
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': Mock(OcrEngine=Mock(
                try_create_from_language=Mock(return_value=None),
                try_create_from_user_profile_languages=Mock(return_value=mock_engine)
            )),
            'winsdk.windows.globalization': Mock(Language=Mock())
        }):
            ocr = WindowsOCR()
            assert ocr.is_available() is True
            assert ocr._engine == mock_engine

    def test_read_returns_empty_when_unavailable(self):
        """Test read returns empty list when OCR unavailable."""
        ocr = WindowsOCR()
        ocr._available = False
        result = ocr.read(b'', 100, 100)
        assert result == []

    def test_read_with_details_returns_empty_when_unavailable(self):
        """Test read_with_details returns empty list when OCR unavailable."""
        ocr = WindowsOCR()
        ocr._available = False
        result = ocr.read_with_details(b'', 100, 100)
        assert result == []


class TestOfflineOCR:
    """Tests for OfflineOCR class."""

    def test_backend_priority_windows_first(self):
        """Test WindowsOCR is tried first as primary backend."""
        # Mock WindowsOCR as available
        mock_windows_engine = Mock()
        mock_windows_engine.recognizer_language.display_name = "English (United States)"
        
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': Mock(OcrEngine=Mock(
                try_create_from_language=Mock(return_value=mock_windows_engine),
                try_create_from_user_profile_languages=Mock(return_value=None)
            )),
            'winsdk.windows.globalization': Mock(Language=Mock())
        }):
            with patch('shutil.which', return_value=None):  # Tesseract not available
                ocr = OfflineOCR()
                assert ocr.is_available() is True
                assert ocr._primary is not None
                assert ocr._primary.__class__.__name__ == "WindowsOCR"

    def test_backend_fallback_to_tesseract(self):
        """Test falls back to Tesseract when Windows OCR unavailable."""
        # Need to mock winsdk such that OcrEngine returns None
        mock_ocr_module = Mock()
        mock_ocr_module.OcrEngine = Mock(
            try_create_from_language=Mock(return_value=None),
            try_create_from_user_profile_languages=Mock(return_value=None)
        )
        mock_globalization = Mock()
        mock_globalization.Language = Mock()
        
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': mock_ocr_module,
            'winsdk.windows.globalization': mock_globalization,
            'winsdk': Mock()
        }):
            with patch('shutil.which', return_value='/usr/bin/tesseract'):
                with patch('subprocess.run') as mock_run:
                    mock_run.return_value.returncode = 0
                    with patch.dict('sys.modules', {'pytesseract': Mock()}):
                        ocr = OfflineOCR()
                        assert ocr.is_available() is True
                        assert ocr._primary is not None
                        assert ocr._primary.__class__.__name__ == "TesseractOCR"

    def test_backend_fallback_to_easyocr(self):
        """Test falls back to EasyOCR when others unavailable."""
        mock_ocr_module = Mock()
        mock_ocr_module.OcrEngine = Mock(
            try_create_from_language=Mock(return_value=None),
            try_create_from_user_profile_languages=Mock(return_value=None)
        )
        mock_globalization = Mock()
        mock_globalization.Language = Mock()
        
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': mock_ocr_module,
            'winsdk.windows.globalization': mock_globalization,
            'winsdk': Mock(),
            'pytesseract': None
        }):
            with patch.dict('sys.modules', {'easyocr': Mock(Reader=Mock())}):
                ocr = OfflineOCR()
                assert ocr.is_available() is True
                assert ocr._primary is not None
                assert ocr._primary.__class__.__name__ == "EasyOCR"

    def test_is_available_false_when_all_unavailable(self):
        """Test is_available returns False when all backends unavailable."""
        mock_ocr_module = Mock()
        mock_ocr_module.OcrEngine = Mock(
            try_create_from_language=Mock(return_value=None),
            try_create_from_user_profile_languages=Mock(return_value=None)
        )
        mock_globalization = Mock()
        mock_globalization.Language = Mock()
        
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': mock_ocr_module,
            'winsdk.windows.globalization': mock_globalization,
            'winsdk': Mock(),
            'pytesseract': None,
            'easyocr': None
        }):
            ocr = OfflineOCR()
            assert ocr.is_available() is False

    def test_read_returns_empty_when_unavailable(self):
        """Test read returns empty list when no backends available."""
        with patch.dict('sys.modules', {
            'winsdk': None,
            'pytesseract': None,
            'easyocr': None
        }):
            ocr = OfflineOCR()
            result = ocr.read(b'', 100, 100)
            assert result == []

    def test_is_available_sync_windows_ocr(self):
        """Test is_available_sync detects Windows OCR."""
        mock_engine = Mock()
        with patch.dict('sys.modules', {
            'winsdk.windows.media.ocr': Mock(OcrEngine=Mock(
                try_create_from_language=Mock(return_value=mock_engine)
            )),
            'winsdk.windows.globalization': Mock(Language=Mock())
        }):
            ocr = OfflineOCR()
            assert ocr.is_available_sync() is True

    def test_is_available_sync_tesseract(self):
        """Test is_available_sync detects Tesseract."""
        with patch.dict('sys.modules', {
            'winsdk': None
        }):
            with patch('shutil.which', return_value='/usr/bin/tesseract'):
                ocr = OfflineOCR()
                assert ocr.is_available_sync() is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])