"""
Unit tests for PersonalizationSkill (Phase 5.8-B).

Verifies:
- Schema correctness and runtime parameter validation
- Theme mutation:
  - dark writes 0/0 to AppsUseLightTheme & SystemUsesLightTheme
  - light writes 1/1 to AppsUseLightTheme & SystemUsesLightTheme
  - invalid mode rejected
  - read-back verification success & failure
- Taskbar mutation:
  - left writes 0 to TaskbarAl
  - center writes 1 to TaskbarAl
  - invalid alignment rejected
  - WM_SETTINGCHANGE notification broadcast invoked
  - read-back verification success & failure
- Wallpaper mutation:
  - valid image accepted (.jpg, .jpeg, .png, .bmp)
  - nonexistent path rejected
  - directory rejected
  - URL rejected
  - unsafe command-like input rejected
  - non-image extensions rejected
  - Win32 SystemParametersInfoW invocation verified
- Strict isolation: Windows APIs are mocked; no real user settings modified.
- No subprocess or shell execution.
"""
import inspect
import os
import sys
import tempfile
from unittest.mock import MagicMock, patch, call
import pytest

from nova.skills.system.personalization import (
    PersonalizationSkill,
    THEME_REG_KEY,
    TASKBAR_REG_KEY,
    SPI_SETDESKWALLPAPER,
    SPIF_UPDATEINIFILE,
    SPIF_SENDCHANGE,
)


class TestPersonalizationSkillSchema:
    def test_schema_structure(self):
        skill = PersonalizationSkill()
        schema = skill.parameters_schema
        assert schema["type"] == "object"
        assert schema["required"] == ["feature"]
        assert schema["additionalProperties"] is False
        assert "feature" in schema["properties"]
        assert "mode" in schema["properties"]
        assert "alignment" in schema["properties"]
        assert "path" in schema["properties"]

    def test_validate_valid_theme(self):
        skill = PersonalizationSkill()
        assert skill.validate({"feature": "theme", "mode": "dark"}) is True
        assert skill.validate({"feature": "theme", "mode": "light"}) is True

    def test_validate_valid_taskbar(self):
        skill = PersonalizationSkill()
        assert skill.validate({"feature": "taskbar", "alignment": "left"}) is True
        assert skill.validate({"feature": "taskbar", "alignment": "center"}) is True

    def test_validate_valid_wallpaper(self, tmp_path):
        skill = PersonalizationSkill()
        img_file = tmp_path / "test.png"
        img_file.write_bytes(b"dummy")
        assert skill.validate({"feature": "wallpaper", "path": str(img_file)}) is True

    def test_validate_missing_feature(self):
        skill = PersonalizationSkill()
        with pytest.raises(ValueError, match="missing required 'feature'"):
            skill.validate({})

    def test_validate_invalid_feature(self):
        skill = PersonalizationSkill()
        with pytest.raises(ValueError, match="Invalid feature"):
            skill.validate({"feature": "screensaver"})

    def test_validate_invalid_theme_mode(self):
        skill = PersonalizationSkill()
        with pytest.raises(ValueError, match="mode"):
            skill.validate({"feature": "theme", "mode": "neon"})

    def test_validate_invalid_taskbar_alignment(self):
        skill = PersonalizationSkill()
        with pytest.raises(ValueError, match="alignment"):
            skill.validate({"feature": "taskbar", "alignment": "top"})

    def test_validate_invalid_wallpaper_path(self):
        skill = PersonalizationSkill()
        with pytest.raises(ValueError, match="path"):
            skill.validate({"feature": "wallpaper", "path": ""})


class TestThemeMutation:
    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_theme_dark_writes_zero_and_verifies(self):
        skill = PersonalizationSkill()

        # Mock winreg operations
        reg_state = {"AppsUseLightTheme": 1, "SystemUsesLightTheme": 1}

        def mock_set_value(key, name, reserved, reg_type, val):
            reg_state[name] = val

        def mock_query_value(key, name):
            return (reg_state.get(name, 0), 4)

        with patch("nova.skills.system.personalization.winreg", create=True) as mock_winreg, \
             patch.object(skill, "_broadcast_setting_change") as mock_broadcast:

            mock_winreg.HKEY_CURRENT_USER = 1
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.KEY_QUERY_VALUE = 1
            mock_winreg.REG_DWORD = 4
            mock_winreg.SetValueEx.side_effect = mock_set_value
            mock_winreg.QueryValueEx.side_effect = mock_query_value

            res = skill.execute({"feature": "theme", "mode": "dark"})

            assert res["success"] is True
            assert res["status"] == "ok"
            assert res["mode"] == "dark"
            assert reg_state["AppsUseLightTheme"] == 0
            assert reg_state["SystemUsesLightTheme"] == 0
            mock_broadcast.assert_called_once_with("ImmersiveColorSet")

    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_theme_light_writes_one_and_verifies(self):
        skill = PersonalizationSkill()

        reg_state = {"AppsUseLightTheme": 0, "SystemUsesLightTheme": 0}

        def mock_set_value(key, name, reserved, reg_type, val):
            reg_state[name] = val

        def mock_query_value(key, name):
            return (reg_state.get(name, 1), 4)

        with patch("nova.skills.system.personalization.winreg", create=True) as mock_winreg, \
             patch.object(skill, "_broadcast_setting_change") as mock_broadcast:

            mock_winreg.HKEY_CURRENT_USER = 1
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.KEY_QUERY_VALUE = 1
            mock_winreg.REG_DWORD = 4
            mock_winreg.SetValueEx.side_effect = mock_set_value
            mock_winreg.QueryValueEx.side_effect = mock_query_value

            res = skill.execute({"feature": "theme", "mode": "light"})

            assert res["success"] is True
            assert res["status"] == "ok"
            assert res["mode"] == "light"
            assert reg_state["AppsUseLightTheme"] == 1
            assert reg_state["SystemUsesLightTheme"] == 1
            mock_broadcast.assert_called_once_with("ImmersiveColorSet")

    def test_theme_invalid_mode_rejected(self):
        skill = PersonalizationSkill()
        res = skill.execute({"feature": "theme", "mode": "cyberpunk"})
        assert res["success"] is False
        assert res["status"] == "error"
        assert "mode" in res["message"]

    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_theme_readback_verification_failure(self):
        skill = PersonalizationSkill()

        with patch("nova.skills.system.personalization.winreg", create=True) as mock_winreg, \
             patch.object(skill, "_broadcast_setting_change"):

            mock_winreg.HKEY_CURRENT_USER = 1
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.KEY_QUERY_VALUE = 1
            mock_winreg.REG_DWORD = 4
            mock_winreg.SetValueEx = MagicMock()
            # Read-back simulates value staying at 1 instead of changing to 0
            mock_winreg.QueryValueEx.return_value = (1, 4)

            res = skill.execute({"feature": "theme", "mode": "dark"})
            assert res["success"] is False
            assert res["status"] == "error"
            assert "verification failed" in res["message"].lower()


class TestTaskbarMutation:
    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_taskbar_left_writes_zero_and_verifies(self):
        skill = PersonalizationSkill()

        reg_state = {"TaskbarAl": 1}

        def mock_set_value(key, name, reserved, reg_type, val):
            reg_state[name] = val

        def mock_query_value(key, name):
            return (reg_state.get(name, 0), 4)

        with patch("nova.skills.system.personalization.winreg", create=True) as mock_winreg, \
             patch.object(skill, "_broadcast_setting_change") as mock_broadcast:

            mock_winreg.HKEY_CURRENT_USER = 1
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.KEY_QUERY_VALUE = 1
            mock_winreg.REG_DWORD = 4
            mock_winreg.SetValueEx.side_effect = mock_set_value
            mock_winreg.QueryValueEx.side_effect = mock_query_value

            res = skill.execute({"feature": "taskbar", "alignment": "left"})

            assert res["success"] is True
            assert res["status"] == "ok"
            assert res["alignment"] == "left"
            assert reg_state["TaskbarAl"] == 0
            mock_broadcast.assert_called_once_with("TraySettings")

    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_taskbar_center_writes_one_and_verifies(self):
        skill = PersonalizationSkill()

        reg_state = {"TaskbarAl": 0}

        def mock_set_value(key, name, reserved, reg_type, val):
            reg_state[name] = val

        def mock_query_value(key, name):
            return (reg_state.get(name, 1), 4)

        with patch("nova.skills.system.personalization.winreg", create=True) as mock_winreg, \
             patch.object(skill, "_broadcast_setting_change") as mock_broadcast:

            mock_winreg.HKEY_CURRENT_USER = 1
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.KEY_QUERY_VALUE = 1
            mock_winreg.REG_DWORD = 4
            mock_winreg.SetValueEx.side_effect = mock_set_value
            mock_winreg.QueryValueEx.side_effect = mock_query_value

            res = skill.execute({"feature": "taskbar", "alignment": "center"})

            assert res["success"] is True
            assert res["status"] == "ok"
            assert res["alignment"] == "center"
            assert reg_state["TaskbarAl"] == 1
            mock_broadcast.assert_called_once_with("TraySettings")

    def test_taskbar_invalid_alignment_rejected(self):
        skill = PersonalizationSkill()
        res = skill.execute({"feature": "taskbar", "alignment": "bottom"})
        assert res["success"] is False
        assert res["status"] == "error"
        assert "alignment" in res["message"]

    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_taskbar_readback_verification_failure(self):
        skill = PersonalizationSkill()

        with patch("nova.skills.system.personalization.winreg", create=True) as mock_winreg, \
             patch.object(skill, "_broadcast_setting_change"):

            mock_winreg.HKEY_CURRENT_USER = 1
            mock_winreg.KEY_SET_VALUE = 2
            mock_winreg.KEY_QUERY_VALUE = 1
            mock_winreg.REG_DWORD = 4
            mock_winreg.SetValueEx = MagicMock()
            # Read-back simulates value staying at 0 instead of changing to 1
            mock_winreg.QueryValueEx.return_value = (0, 4)

            res = skill.execute({"feature": "taskbar", "alignment": "center"})
            assert res["success"] is False
            assert res["status"] == "error"
            assert "verification failed" in res["message"].lower()


class TestWallpaperMutation:
    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_wallpaper_valid_image_accepted(self, tmp_path):
        skill = PersonalizationSkill()
        img_file = tmp_path / "nature.jpg"
        img_file.write_bytes(b"\xff\xd8\xff\xe0" + b"\x00" * 100)

        with patch("nova.skills.system.personalization.ctypes", create=True) as mock_ctypes:
            mock_user32 = MagicMock()
            mock_user32.SystemParametersInfoW.return_value = 1  # Success
            mock_ctypes.windll.user32 = mock_user32
            mock_ctypes.c_void_p.return_value = MagicMock()

            res = skill.execute({"feature": "wallpaper", "path": str(img_file)})

            assert res["success"] is True
            assert res["status"] == "ok"
            assert res["feature"] == "wallpaper"
            mock_user32.SystemParametersInfoW.assert_called_once_with(
                SPI_SETDESKWALLPAPER,
                0,
                str(img_file.resolve()),
                SPIF_UPDATEINIFILE | SPIF_SENDCHANGE,
            )

    def test_wallpaper_nonexistent_path_rejected(self):
        skill = PersonalizationSkill()
        res = skill.execute({"feature": "wallpaper", "path": "C:\\nonexistent\\image.png"})
        assert res["success"] is False
        assert res["status"] == "error"
        assert "not found" in res["message"].lower() or "exist" in res["message"].lower()

    def test_wallpaper_directory_rejected(self, tmp_path):
        skill = PersonalizationSkill()
        res = skill.execute({"feature": "wallpaper", "path": str(tmp_path)})
        assert res["success"] is False
        assert res["status"] == "error"
        assert "directory" in res["message"].lower()

    def test_wallpaper_url_rejected(self):
        skill = PersonalizationSkill()
        urls = [
            "http://example.com/wallpaper.png",
            "https://evil.com/bg.jpg",
            "ftp://files.org/image.bmp",
        ]
        for url in urls:
            res = skill.execute({"feature": "wallpaper", "path": url})
            assert res["success"] is False
            assert res["status"] == "error"

    def test_wallpaper_unsafe_command_strings_rejected(self):
        skill = PersonalizationSkill()
        unsafe_paths = [
            "C:\\Pictures\\wall.png; calc.exe",
            "C:\\Pictures\\wall.png & cmd.exe",
            "C:\\Pictures\\wall.png | powershell",
            "`whoami`.png",
            "$(calc).png",
            "C:\\Pictures\\wall.png\nshutdown /s",
        ]
        for p in unsafe_paths:
            res = skill.execute({"feature": "wallpaper", "path": p})
            assert res["success"] is False
            assert res["status"] == "error"

    def test_wallpaper_disallowed_extension_rejected(self, tmp_path):
        skill = PersonalizationSkill()
        exe_file = tmp_path / "malware.exe"
        exe_file.write_bytes(b"MZ...")
        res = skill.execute({"feature": "wallpaper", "path": str(exe_file)})
        assert res["success"] is False
        assert res["status"] == "error"
        assert "unsupported" in res["message"].lower() or "extension" in res["message"].lower()

    @patch("nova.skills.system.personalization.sys.platform", "win32")
    def test_wallpaper_win32_api_failure(self, tmp_path):
        skill = PersonalizationSkill()
        img_file = tmp_path / "photo.png"
        img_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 50)

        with patch("nova.skills.system.personalization.ctypes", create=True) as mock_ctypes:
            mock_user32 = MagicMock()
            mock_user32.SystemParametersInfoW.return_value = 0  # 0 indicates Win32 failure
            mock_ctypes.windll.user32 = mock_user32
            mock_ctypes.GetLastError.return_value = 5

            res = skill.execute({"feature": "wallpaper", "path": str(img_file)})
            assert res["success"] is False
            assert res["status"] == "error"
            assert "systemparametersinfow failed" in res["message"].lower()


class TestPersonalizationSecurity:
    def test_no_subprocess_or_shell(self):
        """Verify personalization.py source does not use subprocess, shell=True, or os.system."""
        from nova.skills.system import personalization
        source = inspect.getsource(personalization)
        assert "shell=True" not in source
        assert "subprocess" not in source
        assert "os.system" not in source
        assert "cmd.exe" not in source
        assert "powershell" not in source.lower()
