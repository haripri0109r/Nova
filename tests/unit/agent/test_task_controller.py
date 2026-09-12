"""Unit tests for TaskController."""
import pytest
import asyncio
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nova.agent.task_controller import TaskController, TaskPaused, TaskCancelled


@pytest.mark.asyncio
async def test_initial_state():
    ctrl = TaskController('task-1')
    assert ctrl.task_id == 'task-1'
    assert not ctrl.is_paused
    assert not ctrl.is_cancelled
    # checks should not raise
    await ctrl.check_pause()
    await ctrl.check_cancel()


@pytest.mark.asyncio
async def test_pause():
    ctrl = TaskController('task-1')
    await ctrl.pause()
    assert ctrl.is_paused
    with pytest.raises(TaskPaused) as exc:
        await ctrl.check_pause()
    assert exc.value.task_id == 'task-1'
    # cancel not set
    assert not ctrl.is_cancelled
    await ctrl.check_cancel()  # should not raise


@pytest.mark.asyncio
async def test_cancel():
    ctrl = TaskController('task-2')
    await ctrl.cancel()
    assert ctrl.is_cancelled
    assert ctrl.is_paused  # cancel implies pause
    with pytest.raises(TaskCancelled) as exc:
        await ctrl.check_cancel()
    assert exc.value.task_id == 'task-2'
    with pytest.raises(TaskPaused):
        await ctrl.check_pause()


@pytest.mark.asyncio
async def test_repeated_pause():
    ctrl = TaskController('task-3')
    await ctrl.pause()
    await ctrl.pause()  # second pause should be idempotent
    assert ctrl.is_paused
    with pytest.raises(TaskPaused):
        await ctrl.check_pause()


@pytest.mark.asyncio
async def test_repeated_cancel():
    ctrl = TaskController('task-4')
    await ctrl.cancel()
    await ctrl.cancel()
    assert ctrl.is_cancelled
    with pytest.raises(TaskCancelled):
        await ctrl.check_cancel()


@pytest.mark.asyncio
async def test_pause_cancel_checks():
    ctrl = TaskController('task-5')
    await ctrl.pause()
    with pytest.raises(TaskPaused):
        await ctrl.check_pause()
    await ctrl.resume()
    # after resume, checks should pass
    await ctrl.check_pause()
    await ctrl.check_cancel()


@pytest.mark.asyncio
async def test_independent_controllers():
    ctrl1 = TaskController('task-a')
    ctrl2 = TaskController('task-b')
    await ctrl1.pause()
    await ctrl2.cancel()
    assert ctrl1.is_paused
    assert not ctrl1.is_cancelled
    assert ctrl2.is_cancelled
    assert ctrl2.is_paused
    with pytest.raises(TaskPaused):
        await ctrl1.check_pause()
    with pytest.raises(TaskCancelled):
        await ctrl2.check_cancel()
    # ctrl2 check_pause also raises because cancel implies pause
    with pytest.raises(TaskPaused):
        await ctrl2.check_pause()