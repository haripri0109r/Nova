"""
Unit tests for AudioSkill (Phase 5.8-C).

Verifies:
- Skill registration in SkillRegistry and alias resolution
- Strict parameter schema validation (additionalProperties: False)
- Master volume read / set / adjust / mute / unmute with mock boundaries
- Device enumeration (outputs and inputs)
- Microphone status and control (set volume, mute, unmute)
- Deterministic device resolution rules (exact, normalized, unique substring, ambiguous failure)
- Default audio device switching restriction probe:
  - Validates target device against enumerated active devices
  - Rejects unknown / ambiguous target device
  - Returns honest status='restricted' and navigates to ms-settings:sound
  - Never fakes success
"""

from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from nova.skills.base import BaseSkill
from nova.skills.registry import registry
from nova.skills.system.audio import (
    AudioSkill,
    _parse_step_amount,
    resolve_device_name,
)


@pytest.fixture
def skill() -> AudioSkill:
    return AudioSkill()


# ============================================================================
# 1. Registration & Base Interface Tests
# ============================================================================


def test_audio_skill_registration(skill: AudioSkill):
    """AudioSkill must be registered in SkillRegistry with canonical intent 'audio'."""
    retrieved = registry.get("audio")
    assert retrieved is not None
    assert isinstance(retrieved, AudioSkill)
    assert retrieved.intent == "audio"
    assert "audio" in retrieved.description.lower()


def test_audio_skill_alias_resolution():
    """SkillRegistry must resolve 'audio_control' alias to 'audio'."""
    retrieved = registry.get("audio_control")
    assert retrieved is not None
    assert isinstance(retrieved, AudioSkill)


def test_audio_skill_can_handle(skill: AudioSkill):
    """can_handle must accept audio and related audio control intents."""
    assert skill.can_handle({"intent": "audio"}) is True
    assert skill.can_handle({"intent": "audio_control"}) is True
    assert skill.can_handle({"intent": "set_volume"}) is True
    assert skill.can_handle({"intent": "display"}) is False


# ============================================================================
# 2. Schema & Parameter Validation Tests
# ============================================================================


def test_audio_schema_structure(skill: AudioSkill):
    """Schema must define additionalProperties: False and require action."""
    schema = skill.parameters_schema
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "action" in schema["required"]
    assert "get_volume" in schema["properties"]["action"]["enum"]
    assert "set_default_output" in schema["properties"]["action"]["enum"]
    assert "list_inputs" in schema["properties"]["action"]["enum"]


def test_audio_schema_rejects_missing_action(skill: AudioSkill):
    """Validation must raise ValueError if action is missing."""
    with pytest.raises(ValueError, match="missing required 'action' parameter"):
        skill.validate({})


def test_audio_schema_rejects_invalid_action(skill: AudioSkill):
    """Validation must raise ValueError for unknown action."""
    with pytest.raises(ValueError, match="invalid action"):
        skill.validate({"action": "blow_speakers"})


def test_audio_schema_rejects_unexpected_properties(skill: AudioSkill):
    """Validation must reject extra parameters under additionalProperties: False."""
    with pytest.raises(ValueError, match="Unexpected parameter 'injection'"):
        skill.validate({"action": "get_volume", "injection": "powershell -c evil"})


def test_audio_schema_validates_set_volume_level(skill: AudioSkill):
    """set_volume requires integer level between 0 and 100."""
    with pytest.raises(ValueError, match="requires 'level' parameter"):
        skill.validate({"action": "set_volume"})

    with pytest.raises(ValueError, match="'level' must be between 0 and 100"):
        skill.validate({"action": "set_volume", "level": 120})

    with pytest.raises(ValueError, match="'level' must be between 0 and 100"):
        skill.validate({"action": "set_volume", "level": -5})

    assert skill.validate({"action": "set_volume", "level": 40}) is True


def test_audio_schema_validates_set_mic_volume(skill: AudioSkill):
    """set_mic_volume requires integer level between 0 and 100."""
    with pytest.raises(ValueError, match="requires 'level' parameter"):
        skill.validate({"action": "set_mic_volume"})

    assert skill.validate({"action": "set_mic_volume", "level": 80}) is True


def test_audio_schema_validates_set_default_output(skill: AudioSkill):
    """set_default_output requires non-empty string device_name."""
    with pytest.raises(ValueError, match="requires 'device_name' parameter"):
        skill.validate({"action": "set_default_output"})

    with pytest.raises(ValueError, match="'device_name' must be a non-empty string"):
        skill.validate({"action": "set_default_output", "device_name": ""})

    assert skill.validate({"action": "set_default_output", "device_name": "Speakers"}) is True


# ============================================================================
# 3. Deterministic Device Name Resolution Rules
# ============================================================================


def test_device_name_exact_match():
    devices = [
        {"name": "Realtek High Definition Audio", "id": "dev1"},
        {"name": "Headphones (WH-1000XM4)", "id": "dev2"},
    ]
    matched, err = resolve_device_name("Headphones (WH-1000XM4)", devices)
    assert err is None
    assert matched is not None
    assert matched["id"] == "dev2"


def test_device_name_normalized_case_insensitive():
    devices = [
        {"name": "Realtek High Definition Audio", "id": "dev1"},
        {"name": "Speakers (Audio Device)", "id": "dev2"},
    ]
    matched, err = resolve_device_name("speakers (audio device)", devices)
    assert err is None
    assert matched is not None
    assert matched["id"] == "dev2"


def test_device_name_unique_substring_match():
    devices = [
        {"name": "Realtek(R) Audio", "id": "dev1"},
        {"name": "Sony WH-1000XM4 Bluetooth Headphones", "id": "dev2"},
    ]
    matched, err = resolve_device_name("headphones", devices)
    assert err is None
    assert matched is not None
    assert matched["id"] == "dev2"


def test_device_name_ambiguous_match_rejection():
    """Ambiguous query matching multiple devices must be rejected deterministically."""
    devices = [
        {"name": "USB Audio Speakers", "id": "dev1"},
        {"name": "Realtek Speakers", "id": "dev2"},
    ]
    matched, err = resolve_device_name("speakers", devices)
    assert matched is None
    assert err is not None
    assert "Ambiguous" in err
    assert "USB Audio Speakers" in err
    assert "Realtek Speakers" in err


def test_device_name_no_match():
    devices = [{"name": "Speakers", "id": "dev1"}]
    matched, err = resolve_device_name("airpods", devices)
    assert matched is None
    assert err is not None
    assert "No audio device found matching 'airpods'" in err


# ============================================================================
# 4. Master Volume Unit Tests (Mocked Core Audio Boundary)
# ============================================================================


def test_get_volume_success(skill: AudioSkill):
    mock_endpoint = MagicMock()
    mock_endpoint.GetMasterVolumeLevelScalar.return_value = 0.45
    mock_endpoint.GetMute.return_value = 0

    with patch("nova.skills.system.audio._get_master_endpoint_volume", return_value=mock_endpoint):
        res = skill.execute({"action": "get_volume"})
        assert res["status"] == "ok"
        assert res["volume"] == 45
        assert res["muted"] is False
        assert "45%" in res["message"]


def test_set_volume_with_readback(skill: AudioSkill):
    mock_endpoint = MagicMock()
    mock_endpoint.GetMasterVolumeLevelScalar.return_value = 0.60

    with patch("nova.skills.system.audio._get_master_endpoint_volume", return_value=mock_endpoint):
        res = skill.execute({"action": "set_volume", "level": 60})
        assert res["status"] == "ok"
        assert res["volume"] == 60
        assert res["verified"] is True
        mock_endpoint.SetMasterVolumeLevelScalar.assert_called_once_with(0.60, None)


def test_mute_and_unmute(skill: AudioSkill):
    mock_endpoint = MagicMock()
    mock_endpoint.GetMute.return_value = 1

    with patch("nova.skills.system.audio._get_master_endpoint_volume", return_value=mock_endpoint):
        res = skill.execute({"action": "mute"})
        assert res["status"] == "ok"
        assert res["muted"] is True
        mock_endpoint.SetMute.assert_called_with(1, None)

    mock_endpoint.GetMute.return_value = 0
    with patch("nova.skills.system.audio._get_master_endpoint_volume", return_value=mock_endpoint):
        res = skill.execute({"action": "unmute"})
        assert res["status"] == "ok"
        assert res["muted"] is False
        mock_endpoint.SetMute.assert_called_with(0, None)


# ============================================================================
# 5. Microphone Unit Tests
# ============================================================================


def test_get_mic_status(skill: AudioSkill):
    mock_endpoint = MagicMock()
    mock_endpoint.GetMasterVolumeLevelScalar.return_value = 0.75
    mock_endpoint.GetMute.return_value = 0

    with patch("nova.skills.system.audio._get_microphone_endpoint_volume", return_value=mock_endpoint):
        res = skill.execute({"action": "get_mic_status"})
        assert res["status"] == "ok"
        assert res["volume"] == 75
        assert res["muted"] is False
        assert "75%" in res["message"]


def test_mute_mic(skill: AudioSkill):
    mock_endpoint = MagicMock()
    mock_endpoint.GetMute.return_value = 1

    with patch("nova.skills.system.audio._get_microphone_endpoint_volume", return_value=mock_endpoint):
        res = skill.execute({"action": "mute_mic"})
        assert res["status"] == "ok"
        assert res["muted"] is True
        mock_endpoint.SetMute.assert_called_once_with(1, None)


# ============================================================================
# 6. Default Audio Endpoint Switching Restriction Probe
# ============================================================================


def test_set_default_output_honest_restriction(skill: AudioSkill):
    """
    Default audio switching must:
    1. Resolve device against enumerated active devices.
    2. Acknowledge Windows restriction on background programmatic switching.
    3. Return status='restricted', target_uri='ms-settings:sound'.
    4. Open Sound Settings rather than faking mutation.
    """
    mock_devices = [
        {"name": "Speakers (Realtek Audio)", "id": "dev_spk"},
        {"name": "Headphones (WH-1000XM4)", "id": "dev_hp"},
    ]

    with patch("nova.skills.system.audio._enumerate_devices", return_value=mock_devices), \
         patch("os.startfile", create=True) as mock_startfile:
        res = skill.execute({"action": "set_default_output", "device_name": "headphones"})
        assert res["status"] == "restricted"
        assert res["action"] == "navigated"
        assert res["target_uri"] == "ms-settings:sound"
        assert res["target_device"] == "Headphones (WH-1000XM4)"
        assert "restricts" in res["message"].lower()
        mock_startfile.assert_called_once_with("ms-settings:sound")
