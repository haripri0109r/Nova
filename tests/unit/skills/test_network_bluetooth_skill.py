"""
Unit tests for Phase 5.8-D: WifiSkill, BluetoothSkill, and NetworkSkill.

Tests:
- Parameter schema enforcement and validation.
- can_handle intent routing.
- Subprocess execution safety (no shell=True, input validation).
- Access-denied / elevation detection -> status="restricted".
- Real-time read-back state verification.
- Malicious host injection rejection in NetworkSkill.
"""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch
import pytest

from nova.skills.system.wifi import WifiSkill, _sanitize_ssid
from nova.skills.system.bluetooth import BluetoothSkill
from nova.skills.system.network import NetworkSkill, _validate_host


# =============================================================================
# WifiSkill Tests
# =============================================================================


@pytest.fixture
def wifi_skill() -> WifiSkill:
    return WifiSkill()


def test_wifi_can_handle(wifi_skill: WifiSkill):
    assert wifi_skill.can_handle({"intent": "wifi"}) is True
    assert wifi_skill.can_handle({"intent": "wifi_control"}) is True
    assert wifi_skill.can_handle({"intent": "bluetooth"}) is False


def test_wifi_unknown_action(wifi_skill: WifiSkill):
    res = wifi_skill.execute({"action": "invalid_action"})
    assert res["status"] == "error"
    assert "Unknown wifi action" in res["message"]


def test_wifi_sanitize_ssid():
    assert _sanitize_ssid("Home_WiFi-5G") == "Home_WiFi-5G"
    assert _sanitize_ssid("My Network (Guest)") == "My Network (Guest)"
    with pytest.raises(ValueError):
        _sanitize_ssid("Network; rm -rf /")
    with pytest.raises(ValueError):
        _sanitize_ssid("SSID&calc.exe")


@patch("nova.skills.system.wifi.sys.platform", "win32")
@patch("nova.skills.system.wifi._get_wlan_state")
def test_wifi_status_connected(mock_state, wifi_skill: WifiSkill):
    mock_state.return_value = {
        "available": True,
        "interface": "Wi-Fi",
        "state": "connected",
        "ssid": "Office_Net",
    }
    res = wifi_skill.execute({"action": "status"})
    assert res["status"] == "ok"
    assert res["connected"] is True
    assert res["ssid"] == "Office_Net"
    assert res["wifi_state"] == "connected"


@patch("nova.skills.system.wifi.sys.platform", "win32")
@patch("nova.skills.system.wifi._find_wlan_interface", return_value="Wi-Fi")
@patch("nova.skills.system.wifi._run")
@patch("nova.skills.system.wifi._get_netsh_interface_state", return_value="enabled")
def test_wifi_enable_success(mock_state, mock_run, mock_iface, wifi_skill: WifiSkill):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["netsh"], returncode=0, stdout="", stderr=""
    )
    res = wifi_skill.execute({"action": "enable"})
    assert res["status"] == "ok"
    assert res["action"] == "enable"
    assert res["verified_state"] == "enabled"


@patch("nova.skills.system.wifi.sys.platform", "win32")
@patch("nova.skills.system.wifi._find_wlan_interface", return_value="Wi-Fi")
@patch("nova.skills.system.wifi._run")
def test_wifi_toggle_access_denied(mock_run, mock_iface, wifi_skill: WifiSkill):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["netsh"], returncode=1, stdout="", stderr="An administrator is required to complete this operation."
    )
    res = wifi_skill.execute({"action": "enable"})
    assert res["status"] == "restricted"
    assert "Administrator permissions required" in res["message"]
    assert res.get("settings_fallback") == "ms-settings:network-wifi"


@patch("nova.skills.system.wifi.sys.platform", "win32")
@patch("nova.skills.system.wifi._run")
def test_wifi_connect_profile_not_found(mock_run, wifi_skill: WifiSkill):
    mock_run.return_value = subprocess.CompletedProcess(
        args=["netsh"], returncode=1, stdout="Profile 'UnknownNet' is not found.", stderr=""
    )
    res = wifi_skill.execute({"action": "connect", "ssid": "UnknownNet"})
    assert res["status"] == "restricted"
    assert "not found" in res["message"].lower()
    assert res.get("settings_fallback") == "ms-settings:network-wifi"


@patch("nova.skills.system.wifi.sys.platform", "win32")
@patch("nova.skills.system.wifi._run")
@patch("nova.skills.system.wifi._get_wlan_state")
def test_wifi_connect_success(mock_wlan, mock_run, wifi_skill: WifiSkill):
    # Profile check returns success, connect returns success
    mock_run.return_value = subprocess.CompletedProcess(
        args=["netsh"], returncode=0, stdout="Connection request was completed successfully.", stderr=""
    )
    mock_wlan.return_value = {
        "available": True,
        "connected": True,
        "ssid": "TargetNetwork",
        "state": "connected",
    }
    res = wifi_skill.execute({"action": "connect", "ssid": "TargetNetwork"})
    assert res["status"] == "ok"
    assert res["ssid"] == "TargetNetwork"


# =============================================================================
# BluetoothSkill Tests
# =============================================================================


@pytest.fixture
def bluetooth_skill() -> BluetoothSkill:
    return BluetoothSkill()


def test_bluetooth_can_handle(bluetooth_skill: BluetoothSkill):
    assert bluetooth_skill.can_handle({"intent": "bluetooth"}) is True
    assert bluetooth_skill.can_handle({"intent": "bluetooth_control"}) is True
    assert bluetooth_skill.can_handle({"intent": "wifi"}) is False


def test_bluetooth_unknown_action(bluetooth_skill: BluetoothSkill):
    res = bluetooth_skill.execute({"action": "pair"})
    assert res["status"] == "error"
    assert "Unknown bluetooth action" in res["message"]


@patch("nova.skills.system.bluetooth.sys.platform", "win32")
@patch("nova.skills.system.bluetooth._query_pnp_bluetooth_radio")
def test_bluetooth_status_ok(mock_query, bluetooth_skill: BluetoothSkill):
    mock_query.return_value = ("OK", "Intel Wireless Bluetooth", "USB\\VID_8087&PID_0029\\5&...")
    res = bluetooth_skill.execute({"action": "status"})
    assert res["status"] == "ok"
    assert res["bluetooth_state"] == "enabled"
    assert "Intel" in res["adapter_name"]


@patch("nova.skills.system.bluetooth.sys.platform", "win32")
@patch("nova.skills.system.bluetooth._query_pnp_bluetooth_radio")
def test_bluetooth_status_restricted(mock_query, bluetooth_skill: BluetoothSkill):
    mock_query.return_value = ("RESTRICTED", None, None)
    res = bluetooth_skill.execute({"action": "status"})
    assert res["status"] == "restricted"
    assert res.get("settings_fallback") == "ms-settings:bluetooth"


@patch("nova.skills.system.bluetooth.sys.platform", "win32")
@patch("nova.skills.system.bluetooth._query_pnp_bluetooth_radio")
@patch("nova.skills.system.bluetooth._run_ps")
def test_bluetooth_enable_success(mock_ps, mock_query, bluetooth_skill: BluetoothSkill):
    mock_query.side_effect = [
        ("Error", "Intel Wireless Bluetooth", "USB\\VID_8087"),  # pre-toggle
        ("OK", "Intel Wireless Bluetooth", "USB\\VID_8087"),     # post-toggle read-back
    ]
    mock_ps.return_value = subprocess.CompletedProcess(
        args=["powershell"], returncode=0, stdout="", stderr=""
    )
    res = bluetooth_skill.execute({"action": "enable"})
    assert res["status"] == "ok"
    assert res["action"] == "enable"
    assert res["verified_status"] == "OK"


# =============================================================================
# NetworkSkill Tests
# =============================================================================


@pytest.fixture
def network_skill() -> NetworkSkill:
    return NetworkSkill()


def test_network_can_handle(network_skill: NetworkSkill):
    assert network_skill.can_handle({"intent": "network"}) is True
    assert network_skill.can_handle({"intent": "network_control"}) is True
    assert network_skill.can_handle({"intent": "network_status"}) is True


def test_network_host_validation():
    assert _validate_host("8.8.8.8") == "8.8.8.8"
    assert _validate_host("127.0.0.1") == "127.0.0.1"
    assert _validate_host("google.com") == "google.com"
    assert _validate_host("dns.google.com") == "dns.google.com"

    # Injections must be rejected
    with pytest.raises(ValueError):
        _validate_host("8.8.8.8; calc.exe")
    with pytest.raises(ValueError):
        _validate_host("127.0.0.1 && dir")
    with pytest.raises(ValueError):
        _validate_host("host|cmd")
    with pytest.raises(ValueError):
        _validate_host("")


@patch("nova.skills.system.network.sys.platform", "win32")
@patch("nova.skills.system.network._parse_ipconfig")
def test_network_status_connected(mock_ipconfig, network_skill: NetworkSkill):
    mock_ipconfig.return_value = [
        {
            "name": "Wi-Fi",
            "type": "wifi",
            "connected": True,
            "ipv4": "192.168.1.150",
            "gateway": "192.168.1.1",
        }
    ]
    res = network_skill.execute({"action": "status"})
    assert res["status"] == "ok"
    assert res["connected"] is True
    assert res["ipv4"] == "192.168.1.150"
    assert res["gateway"] == "192.168.1.1"


@patch("nova.skills.system.network.sys.platform", "win32")
@patch("nova.skills.system.network._parse_dns_servers")
def test_network_dns(mock_dns, network_skill: NetworkSkill):
    mock_dns.return_value = ["1.1.1.1", "1.0.0.1"]
    res = network_skill.execute({"action": "dns"})
    assert res["status"] == "ok"
    assert res["dns_servers"] == ["1.1.1.1", "1.0.0.1"]
    assert res["count"] == 2


@patch("nova.skills.system.network.sys.platform", "win32")
@patch("nova.skills.system.network._run")
def test_network_ping_parsing(mock_run, network_skill: NetworkSkill):
    ping_output = (
        "Pinging 8.8.8.8 with 32 bytes of data:\n"
        "Reply from 8.8.8.8: bytes=32 time=14ms TTL=117\n"
        "Reply from 8.8.8.8: bytes=32 time=15ms TTL=117\n"
        "Reply from 8.8.8.8: bytes=32 time=13ms TTL=117\n"
        "Reply from 8.8.8.8: bytes=32 time=16ms TTL=117\n\n"
        "Ping statistics for 8.8.8.8:\n"
        "    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),\n"
        "Approximate round trip times in milli-seconds:\n"
        "    Minimum = 13ms, Maximum = 16ms, Average = 14ms\n"
    )
    mock_run.return_value = subprocess.CompletedProcess(
        args=["ping"], returncode=0, stdout=ping_output, stderr=""
    )
    res = network_skill.execute({"action": "ping", "host": "8.8.8.8", "count": 4})
    assert res["status"] == "ok"
    assert res["reachable"] is True
    assert res["packets_sent"] == 4
    assert res["packets_received"] == 4
    assert res["packet_loss_percent"] == 0.0
    assert res["avg_latency_ms"] == 14
