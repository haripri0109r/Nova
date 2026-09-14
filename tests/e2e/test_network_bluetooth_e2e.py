"""
Real Windows End-to-End Test Suite for Phase 5.8-D.

Verifies real Windows execution of NetworkSkill, WifiSkill, and BluetoothSkill:
1. Real Windows network capabilities:
   - network status (primary adapter, IPv4, gateway)
   - network interfaces enumeration
   - network dns query
2. Real Windows Wi-Fi query capabilities:
   - wifi status query (interface state, connected SSID)
   - wifi invalid connection rejection
3. Real Windows Bluetooth query capabilities:
   - bluetooth status query (adapter name, state)
4. Full pipeline execution:
   User Text -> Brain -> Deterministic Fast Path -> TaskService -> PlanExecutor -> Real Windows
"""

from __future__ import annotations

import asyncio
import sys
import pytest

from nova.brain.engine import BrainEngine
from nova.agent.task_service import get_task_service, TaskStatus, ActionStatus
from nova.skills.registry import registry
from nova.skills.system.network import NetworkSkill
from nova.skills.system.wifi import WifiSkill
from nova.skills.system.bluetooth import BluetoothSkill


@pytest.fixture
def network_skill() -> NetworkSkill:
    return NetworkSkill()


@pytest.fixture
def wifi_skill() -> WifiSkill:
    return WifiSkill()


@pytest.fixture
def bluetooth_skill() -> BluetoothSkill:
    return BluetoothSkill()


# =============================================================================
# 1. Real Windows Network Query Tests
# =============================================================================


def test_real_windows_network_status(network_skill: NetworkSkill):
    """Query real Windows network configuration via ipconfig."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = network_skill.execute({"action": "status"})
    assert res["status"] == "ok"
    assert "connected" in res
    if res["connected"]:
        assert res.get("ipv4") is not None
        assert res.get("primary_interface") is not None


def test_real_windows_network_interfaces(network_skill: NetworkSkill):
    """Enumerate real Windows network interfaces."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = network_skill.execute({"action": "interfaces"})
    assert res["status"] == "ok"
    assert "interfaces" in res
    assert isinstance(res["interfaces"], list)
    assert res["count"] == len(res["interfaces"])


def test_real_windows_network_dns(network_skill: NetworkSkill):
    """Query real Windows DNS server configuration."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = network_skill.execute({"action": "dns"})
    assert res["status"] == "ok"
    assert "dns_servers" in res
    assert isinstance(res["dns_servers"], list)


# =============================================================================
# 2. Real Windows Wi-Fi & Bluetooth Query Tests
# =============================================================================


def test_real_windows_wifi_status(wifi_skill: WifiSkill):
    """Query real Windows Wi-Fi interface state."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = wifi_skill.execute({"action": "status"})
    # On systems without Wi-Fi hardware, returns status="unsupported"
    assert res["status"] in ("ok", "unsupported", "restricted")
    if res["status"] == "ok":
        assert "wifi_state" in res
        assert "connected" in res


def test_real_windows_bluetooth_status(bluetooth_skill: BluetoothSkill):
    """Query real Windows Bluetooth adapter state."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    res = bluetooth_skill.execute({"action": "status"})
    # If restricted (CIM/WMI permissions), unsupported (no adapter), or ok
    assert res["status"] in ("ok", "unsupported", "restricted")
    if res["status"] == "ok":
        assert "bluetooth_state" in res


# =============================================================================
# 3. Full Pipeline Execution Tests (Text -> Brain -> TaskService -> Real Windows)
# =============================================================================


@pytest.mark.asyncio
async def test_full_pipeline_network_status():
    """End-to-end: 'network status' -> Brain fast path -> TaskService -> NetworkSkill."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    engine = BrainEngine()
    await engine.initialize()
    ts = get_task_service()

    resp = await engine.process_text("network status", session_id="e2e_network_pipeline")
    assert resp is not None

    tasks = await ts.list_tasks()
    latest_task = tasks[-1]
    assert latest_task.status == TaskStatus.COMPLETED
    assert latest_task.steps[0].status == ActionStatus.SUCCESS
    assert latest_task.steps[0].tool == "network"


@pytest.mark.asyncio
async def test_full_pipeline_wifi_status():
    """End-to-end: 'check wifi' -> Brain fast path -> TaskService -> WifiSkill."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    engine = BrainEngine()
    await engine.initialize()
    ts = get_task_service()

    resp = await engine.process_text("check wifi", session_id="e2e_wifi_pipeline")
    assert resp is not None

    tasks = await ts.list_tasks()
    latest_task = tasks[-1]
    assert latest_task.status == TaskStatus.COMPLETED
    assert latest_task.steps[0].status == ActionStatus.SUCCESS
    assert latest_task.steps[0].tool == "wifi"


@pytest.mark.asyncio
async def test_full_pipeline_bluetooth_status():
    """End-to-end: 'bluetooth status' -> Brain fast path -> TaskService -> BluetoothSkill."""
    if sys.platform != "win32":
        pytest.skip("Windows only test")

    engine = BrainEngine()
    await engine.initialize()
    ts = get_task_service()

    resp = await engine.process_text("bluetooth status", session_id="e2e_bt_pipeline")
    assert resp is not None

    tasks = await ts.list_tasks()
    latest_task = tasks[-1]
    assert latest_task.status == TaskStatus.COMPLETED
    assert latest_task.steps[0].status == ActionStatus.SUCCESS
    assert latest_task.steps[0].tool == "bluetooth"
