"""
Unit tests for event models.
"""
import pytest
from nova.events.events import (
    BaseEvent,
    BatteryLowEvent,
    BatteryCriticalEvent,
    UsbInsertedEvent,
    UsbRemovedEvent,
    WifiConnectedEvent,
    WifiDisconnectedEvent,
    BluetoothConnectedEvent,
    BluetoothDisconnectedEvent,
    VolumeChangedEvent,
    BrightnessChangedEvent,
    ApplicationStartedEvent,
    ApplicationClosedEvent,
    ClipboardChangedEvent,
    ForegroundWindowChangedEvent,
    CpuHighUsageEvent,
    MemoryHighUsageEvent,
    DiskLowSpaceEvent,
    MicrophoneEnabledEvent,
    CameraEnabledEvent,
    ShutdownRequestedEvent,
    RestartRequestedEvent,
    SleepRequestedEvent,
    WakeWordDetectedEvent,
    UserCommandReceivedEvent,
    GoalCompletedEvent,
    GoalFailedEvent,
    WorkflowStartedEvent,
    WorkflowCompletedEvent,
    WorkflowFailedEvent,
    PluginLoadedEvent,
    PluginUnloadedEvent,
    ScheduledEvent,
)


def test_base_event_defaults():
    evt = BaseEvent(source="test", category="test")
    assert evt.event_id
    assert evt.timestamp
    assert evt.priority == 5  # NORMAL
    assert evt.payload == {}
    assert evt.correlation_id is None
    assert evt.metadata == {}


@pytest.mark.parametrize("cls,cat,payload", [
    (BatteryLowEvent, "power", {"level": 10}),
    (BatteryCriticalEvent, "power", {"level": 5}),
    (UsbInsertedEvent, "device", {"device_id": "123", "description": "mouse"}),
    (UsbRemovedEvent, "device", {"device_id": "123"}),
    (WifiConnectedEvent, "network", {"ssid": "home", "bssid": "aa:bb:cc"}),
    (WifiDisconnectedEvent, "network", {"ssid": "home"}),
    (BluetoothConnectedEvent, "device", {"device_name": "mouse", "mac": "aa:bb:cc:dd:ee:ff"}),
    (BluetoothDisconnectedEvent, "device", {"mac": "aa:bb:cc:dd:ee:ff"}),
    (VolumeChangedEvent, "audio", {"level": 50, "muted": False}),
    (BrightnessChangedEvent, "display", {"level": 80}),
    (ApplicationStartedEvent, "application", {"pid": 1234, "name": "code", "exe": "code.exe"}),
    (ApplicationClosedEvent, "application", {"pid": 1234, "name": "code"}),
    (ClipboardChangedEvent, "system", {"content_type": "text", "preview": "hello"}),
    (ForegroundWindowChangedEvent, "system", {"pid": 1234, "title": "VS Code", "exe": "code.exe"}),
    (CpuHighUsageEvent, "health", {"percent": 95.5}),
    (MemoryHighUsageEvent, "health", {"percent": 90.0}),
    (DiskLowSpaceEvent, "health", {"free_bytes": 1024, "total_bytes": 1000000}),
    (MicrophoneEnabledEvent, "privacy", {"enabled": True}),
    (CameraEnabledEvent, "privacy", {"enabled": False}),
    (ShutdownRequestedEvent, "power", {}),
    (RestartRequestedEvent, "power", {}),
    (SleepRequestedEvent, "power", {}),
    (WakeWordDetectedEvent, "voice", {"phrase": "hey nova"}),
    (UserCommandReceivedEvent, "intent", {"text": "open chrome", "intent_id": "open_app"}),
    (GoalCompletedEvent, "goal", {"goal_id": "1", "summary": "done"}),
    (GoalFailedEvent, "goal", {"goal_id": "1", "reason": "timeout"}),
    (WorkflowStartedEvent, "workflow", {"workflow_id": "w1", "name": "morning"}),
    (WorkflowCompletedEvent, "workflow", {"workflow_id": "w1", "result": "ok"}),
    (WorkflowFailedEvent, "workflow", {"workflow_id": "w1", "error": "timeout"}),
    (PluginLoadedEvent, "plugin", {"plugin_name": "demo", "version": "1.0"}),
    (PluginUnloadedEvent, "plugin", {"plugin_name": "demo"}),
    (ScheduledEvent, "scheduler", {"job_id": "job1", "trigger": "cron"}),
])
def test_event_creation(cls, cat, payload):
    evt = cls(source="test", payload=payload)
    assert evt.category == cat
    assert evt.payload == payload
    assert isinstance(evt.event_id, str)
    assert evt.timestamp