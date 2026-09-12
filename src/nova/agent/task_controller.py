"""Task control primitives for pause/cancel."""
from __future__ import annotations
import asyncio
from typing import Optional


class TaskPaused(Exception):
    """Raised when a task is paused."""
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task {task_id} paused")


class TaskCancelled(Exception):
    """Raised when a task is cancelled."""
    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(f"Task {task_id} cancelled")


class TaskController:
    """Controls execution of a single task: pause, cancel, and checks."""

    def __init__(self, task_id: str):
        self._task_id = task_id
        self._pause_event = asyncio.Event()
        self._cancel_event = asyncio.Event()
        self._lock = asyncio.Lock()

    @property
    def task_id(self) -> str:
        return self._task_id

    @property
    def is_paused(self) -> bool:
        return self._pause_event.is_set()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    async def pause(self) -> None:
        """Request the task to pause."""
        async with self._lock:
            self._pause_event.set()

    async def cancel(self) -> None:
        """Request the task to cancel."""
        async with self._lock:
            self._cancel_event.set()
            # Cancelling also implies pause
            self._pause_event.set()

    async def resume(self) -> None:
        """Resume a paused task."""
        async with self._lock:
            self._pause_event.clear()

    async def check_pause(self) -> None:
        """Raise TaskPaused if the task has been paused."""
        if self._pause_event.is_set():
            raise TaskPaused(self._task_id)

    async def check_cancel(self) -> None:
        """Raise TaskCancelled if the task has been cancelled."""
        if self._cancel_event.is_set():
            raise TaskCancelled(self._task_id)

    async def wait_until_resumed(self) -> None:
        """Wait until the task is resumed (pause cleared)."""
        await self._pause_event.wait()
        # When wait returns, the event is set (paused). Wait for clear.
        while self._pause_event.is_set():
            await asyncio.sleep(0.05)


# In-memory registry for active TaskControllers
_controllers: dict[str, TaskController] = {}


def register_task_controller(task_id: str, controller: TaskController) -> None:
    """Register an in-memory task controller for an active task."""
    _controllers[task_id] = controller


def get_task_controller(task_id: str) -> Optional[TaskController]:
    """Retrieve an active in-memory task controller if present."""
    return _controllers.get(task_id)


def remove_task_controller(task_id: str) -> None:
    """Unregister an in-memory task controller."""
    _controllers.pop(task_id, None)