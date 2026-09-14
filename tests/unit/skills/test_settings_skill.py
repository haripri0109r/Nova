"""
Unit tests for SettingsSkill (Phase 5.8-B).

Verifies:
- Schema correctness and parameter validation
- Every allowlisted page resolves correctly
- Deterministic aliases map to canonical pages
- Unknown pages return unsupported
- Arbitrary URIs and injection attempts are rejected
- No subprocess or shell execution is used
- Navigation result is strictly distinct from mutation
- Special handling / honest messaging for protected settings like default_apps
"""
import inspect
import os
import subprocess
from unittest.mock import MagicMock, patch
import pytest

from nova.skills.system.settings import (
    SettingsSkill,
    SETTINGS_URI_MAP,
    SETTINGS_ALIASES,
    resolve_settings_page,
    get_settings_uri,
)


class TestSettingsSkillSchema:
    def test_schema_structure(self):
        skill = SettingsSkill()
        schema = skill.parameters_schema
        assert schema["type"] == "object"
        assert "page" in schema["properties"]
        assert schema["properties"]["page"]["type"] == "string"
        assert schema["required"] == ["page"]
        assert schema["additionalProperties"] is False

    def test_validation_valid_input(self):
        skill = SettingsSkill()
        assert skill.validate({"page": "display"}) is True
        assert skill.validate({"page": "sound"}) is True
        assert skill.validate({"page": "settings"}) is True

    def test_validation_missing_page(self):
        skill = SettingsSkill()
        with pytest.raises(ValueError, match="missing required 'page'"):
            skill.validate({})

    def test_validation_invalid_type(self):
        skill = SettingsSkill()
        with pytest.raises(ValueError, match="'page' must be a string"):
            skill.validate({"page": 123})

    def test_validation_additional_properties(self):
        skill = SettingsSkill()
        with pytest.raises(ValueError, match="Unexpected parameter"):
            skill.validate({"page": "display", "extra": "invalid"})


class TestSettingsSkillResolution:
    def test_every_allowlisted_page_resolves_correctly(self):
        for page_key, expected_uri in SETTINGS_URI_MAP.items():
            resolved = resolve_settings_page(page_key)
            assert resolved == page_key, f"Page key '{page_key}' did not resolve to itself"
            uri = get_settings_uri(resolved)
            assert uri == expected_uri, f"Page '{page_key}' produced '{uri}', expected '{expected_uri}'"
            assert uri.startswith("ms-settings:"), f"URI '{uri}' must start with 'ms-settings:'"

    def test_aliases(self):
        expected_aliases = {
            "audio": "sound",
            "screen": "display",
            "browser": "default_apps",
            "update": "windows_update",
            "dark mode": "dark_mode",
            "darkmode": "dark_mode",
            "theme": "personalization",
            "wallpaper": "background",
        }
        for alias, target in expected_aliases.items():
            resolved = resolve_settings_page(alias)
            assert resolved == target, f"Alias '{alias}' should resolve to '{target}', got '{resolved}'"
            uri = get_settings_uri(resolved)
            assert uri == SETTINGS_URI_MAP[target]

    def test_root_settings_resolution(self):
        assert resolve_settings_page("settings") == "settings"
        assert resolve_settings_page("") is None
        assert get_settings_uri("settings") == "ms-settings:"

    def test_unknown_page_rejected(self):
        assert resolve_settings_page("quantum_teleportation") is None
        assert resolve_settings_page("control_panel_deep_hack") is None
        assert get_settings_uri("unknown_page") is None

    def test_arbitrary_uri_rejected(self):
        malicious_inputs = [
            "ms-settings:display",  # URI directly instead of page name
            "ms-settings://display",
            "http://example.com",
            "https://malicious.site",
            "file:///C:/Windows/System32/cmd.exe",
            "powershell://calc",
            "cmd.exe",
            "display; calc.exe",
            "display && calc",
            "display|notepad",
            "../secret",
            "ms-settings:appsfeatures?param=exploit",
        ]
        for bad_input in malicious_inputs:
            resolved = resolve_settings_page(bad_input)
            assert resolved is None, f"Dangerous input '{bad_input}' should not resolve to any page, got '{resolved}'"


class TestSettingsSkillExecution:
    def test_successful_navigation(self):
        skill = SettingsSkill()
        with patch("nova.skills.system.settings.os.startfile", create=True) as mock_startfile:
            result = skill.execute({"page": "display"})
            assert result["success"] is True
            assert result["status"] == "opened"
            assert result["action"] == "navigated"
            assert result["page"] == "display"
            assert result["uri"] == "ms-settings:display"
            assert "Opened Windows Settings for display" in result["message"]
            assert "changed" not in result["message"].lower()
            mock_startfile.assert_called_once_with("ms-settings:display")

    def test_navigation_with_alias(self):
        skill = SettingsSkill()
        with patch("nova.skills.system.settings.os.startfile", create=True) as mock_startfile:
            result = skill.execute({"page": "audio"})
            assert result["success"] is True
            assert result["page"] == "sound"
            assert result["uri"] == "ms-settings:sound"
            mock_startfile.assert_called_once_with("ms-settings:sound")

    def test_unsupported_page_execution(self):
        skill = SettingsSkill()
        with patch("nova.skills.system.settings.os.startfile", create=True) as mock_startfile:
            result = skill.execute({"page": "nonexistent_setting"})
            assert result["success"] is False
            assert result["status"] == "unsupported"
            assert "available_pages" in result
            mock_startfile.assert_not_called()

    def test_default_apps_honest_messaging(self):
        skill = SettingsSkill()
        with patch("nova.skills.system.settings.os.startfile", create=True) as mock_startfile:
            result = skill.execute({"page": "default_apps"})
            assert result["success"] is True
            assert result["action"] == "navigated"
            assert result["uri"] == "ms-settings:defaultapps"
            assert "protected" in result["note"].lower()
            assert "UserChoice" in result["note"] or "protected" in result["note"]
            mock_startfile.assert_called_once_with("ms-settings:defaultapps")

    def test_navigation_distinct_from_mutation(self):
        """SettingsSkill MUST never claim a setting was mutated or changed."""
        skill = SettingsSkill()
        with patch("nova.skills.system.settings.os.startfile", create=True):
            for page in ["sound", "display", "wifi", "bluetooth", "dark_mode"]:
                result = skill.execute({"page": page})
                msg = result.get("message", "").lower()
                assert "opened" in msg or "navigated" in msg
                assert "changed" not in msg
                assert "modified" not in msg
                assert "applied" not in msg

    def test_no_subprocess_or_shell_in_settings(self):
        """Verify settings.py source does not use subprocess, shell=True, or os.system."""
        from nova.skills.system import settings
        source = inspect.getsource(settings)
        assert "shell=True" not in source
        assert "subprocess.Popen" not in source
        assert "subprocess.run" not in source
        assert "os.system" not in source
        assert "cmd.exe" not in source
        assert "powershell" not in source.lower()
