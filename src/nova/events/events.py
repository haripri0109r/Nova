"""
All Nova events – Pydantic models inheriting from BaseEvent.
"""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from enum import IntEnum
from pydantic import BaseModel, Field, ConfigDict


class Priority(IntEnum):
    LOW = 0
    NORMAL = 5
    HIGH = 10
    CRITICAL = 20


class BaseEvent(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    source: str = Field(..., description="Originating module / component")
    category: str = Field(..., description="Logical grouping, e.g. 'power', 'network'")
    priority: Priority = Field(default=Priority.NORMAL)
    payload: Dict[str, Any] = Field(default_factory=dict)
    correlation_id: Optional[str] = Field(default=None, description="Correlation for request‑response chains")
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------- Power / Battery ----------
class BatteryLowEvent(BaseEvent):
    category: str = "power"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"level": 0})

class BatteryCriticalEvent(BaseEvent):
    category: str = "power"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"level": 0})


# ---------- USB ----------
class UsbInsertedEvent(BaseEvent):
    category: str = "device"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"device_id": "", "description": ""})

class UsbRemovedEvent(BaseEvent):
    category: str = "device"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"device_id": ""})


# ---------- Network ----------
class WifiConnectedEvent(BaseEvent):
    category: str = "network"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"ssid": "", "bssid": ""})

class WifiDisconnectedEvent(BaseEvent):
    category: str = "network"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"ssid": ""})


# ---------- Bluetooth ----------
class BluetoothConnectedEvent(BaseEvent):
    category: str = "device"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"device_name": "", "mac": ""})

class BluetoothDisconnectedEvent(BaseEvent):
    category: str = "device"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"mac": ""})


# ---------- Audio / Display ----------
class VolumeChangedEvent(BaseEvent):
    category: str = "audio"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"level": 0, "muted": False})

class BrightnessChangedEvent(BaseEvent):
    category: str = "display"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"level": 0})


# ---------- Applications ----------
class ApplicationStartedEvent(BaseEvent):
    category: str = "application"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"pid": 0, "name": "", "exe": ""})

class ApplicationClosedEvent(BaseEvent):
    category: str = "application"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"pid": 0, "name": ""})


# ---------- Clipboard / Foreground ----------
class ClipboardChangedEvent(BaseEvent):
    category: str = "system"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"content_type": "", "preview": ""})

class ForegroundWindowChangedEvent(BaseEvent):
    category: str = "system"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"pid": 0, "title": "", "exe": ""})


# ---------- System health ----------
class CpuHighUsageEvent(BaseEvent):
    category: str = "health"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"percent": 0.0})

class MemoryHighUsageEvent(BaseEvent):
    category: str = "health"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"percent": 0.0})

class DiskLowSpaceEvent(BaseEvent):
    category: str = "health"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"free_bytes": 0, "total_bytes": 0})


# ---------- Privacy ----------
class MicrophoneEnabledEvent(BaseEvent):
    category: str = "privacy"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"enabled": True})

class CameraEnabledEvent(BaseEvent):
    category: str = "privacy"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"enabled": True})


# ---------- Power management ----------
class ShutdownRequestedEvent(BaseEvent):
    category: str = "power"
    payload: Dict[str, Any] = Field(default_factory=dict)

class RestartRequestedEvent(BaseEvent):
    category: str = "power"
    payload: Dict[str, Any] = Field(default_factory=dict)

class SleepRequestedEvent(BaseEvent):
    category: str = "power"
    payload: Dict[str, Any] = Field(default_factory=dict)


# ---------- Wake word / Commands ----------
class WakeWordDetectedEvent(BaseEvent):
    category: str = "voice"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"phrase": ""})

class UserCommandReceivedEvent(BaseEvent):
    category: str = "intent"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"text": "", "intent_id": ""})


# ---------- Goals ----------
class GoalCompletedEvent(BaseEvent):
    category: str = "goal"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"goal_id": "", "summary": ""})

class GoalFailedEvent(BaseEvent):
    category: str = "goal"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"goal_id": "", "reason": ""})


# ---------- Workflows ----------
class WorkflowStartedEvent(BaseEvent):
    category: str = "workflow"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"workflow_id": "", "name": ""})

class WorkflowCompletedEvent(BaseEvent):
    category: str = "workflow"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"workflow_id": "", "result": ""})

class WorkflowFailedEvent(BaseEvent):
    category: str = "workflow"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"workflow_id": "", "error": ""})


# ---------- Plugins ----------
class PluginLoadedEvent(BaseEvent):
    category: str = "plugin"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"plugin_name": "", "version": ""})

class PluginUnloadedEvent(BaseEvent):
    category: str = "plugin"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"plugin_name": ""})


# ---------- Intent ----------
class IntentResolvedEvent(BaseEvent):
    category: str = "intent"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"intent": "", "confidence": 0.0, "parameters": {}})


# ---------- Scheduler ----------
class ScheduledEvent(BaseEvent):
    """Generic wrapper for any scheduled job (cron / interval / one‑shot)."""
    category: str = "scheduler"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"job_id": "", "trigger": ""})


# ---------- Task lifecycle ----------
class TaskCreatedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "plan_summary": ""})

class StepStartedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0, "tool": ""})

class StepCompletedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0, "tool": "", "success": True, "detail": ""})

class StepInterruptedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0, "tool": "", "reason": ""})

class TaskPausedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0, "reason": ""})

class TaskCancelledEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0, "reason": ""})

class TaskResumedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0})

class TaskCompletedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "summary": ""})

class TaskFailedEvent(BaseEvent):
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {"task_id": "", "step_index": 0, "error": ""})

class StepRetriedEvent(BaseEvent):
    """Emitted when an INTERRUPTED step is marked PENDING and scheduled for retry."""
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {
        "task_id": "", "step_index": 0, "tool": "", "retry_count": 0,
    })

class StepSkippedEvent(BaseEvent):
    """Emitted when an INTERRUPTED step is marked SKIPPED by user command."""
    category: str = "task"
    payload: Dict[str, Any] = Field(default_factory=lambda: {
        "task_id": "", "step_index": 0, "tool": "", "reason": "",
    })