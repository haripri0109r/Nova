"""Unit tests for TaskRepository."""
import pytest
import tempfile
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'src'))

from nova.agent.models import TaskStatus, TaskRecord, ExecutionContext, ExecutionPlan
from nova.agent.task_repository import SQLiteTaskRepository


@pytest.fixture
def temp_db():
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        db_path = f.name
    yield db_path
    os.unlink(db_path)


def make_record():
    ctx = ExecutionContext(session_id='s1', execution_id='e1')
    plan = ExecutionPlan(actions=[])
    return TaskRecord(plan=plan, context=ctx, max_steps=5, wall_clock_timeout_seconds=30)


def test_create_get_roundtrip(temp_db):
    repo = SQLiteTaskRepository(temp_db)
    rec = make_record()
    task_id = repo.create(rec)
    assert task_id == rec.id
    got = repo.get(task_id)
    assert got is not None
    assert got.id == rec.id
    assert got.status == TaskStatus.RUNNING
    assert got.context.session_id == 's1'
    assert got.max_steps == 5
    assert got.wall_clock_timeout_seconds == 30


def test_update(temp_db):
    repo = SQLiteTaskRepository(temp_db)
    rec = make_record()
    repo.create(rec)
    rec.status = TaskStatus.PAUSED
    rec.current_step = 2
    repo.update(rec)
    got = repo.get(rec.id)
    assert got.status == TaskStatus.PAUSED
    assert got.current_step == 2


def test_list_all(temp_db):
    repo = SQLiteTaskRepository(temp_db)
    rec1 = make_record()
    rec2 = make_record()
    repo.create(rec1)
    repo.create(rec2)
    all_tasks = repo.list()
    assert len(all_tasks) == 2


def test_list_by_status(temp_db):
    repo = SQLiteTaskRepository(temp_db)
    rec1 = make_record()
    rec2 = make_record()
    repo.create(rec1)
    repo.create(rec2)
    repo.update(rec2.__class__(**{**rec2.dict(), 'status': TaskStatus.PAUSED}))
    paused = repo.list(TaskStatus.PAUSED)
    running = repo.list(TaskStatus.RUNNING)
    assert len(paused) == 1
    assert len(running) == 1


def test_missing_returns_none(temp_db):
    repo = SQLiteTaskRepository(temp_db)
    got = repo.get('nonexistent')
    assert got is None


def test_persistence_across_repository_instances(temp_db):
    rec = make_record()
    repo1 = SQLiteTaskRepository(temp_db)
    repo1.create(rec)
    repo2 = SQLiteTaskRepository(temp_db)
    got = repo2.get(rec.id)
    assert got is not None
    assert got.id == rec.id


def test_serialization_integrity(temp_db):
    repo = SQLiteTaskRepository(temp_db)
    rec = make_record()
    rec.context.add_step_result(0, 'toolA', True, {'detail': 'ok'})
    repo.create(rec)
    got = repo.get(rec.id)
    assert len(got.context.step_results) == 1
    assert got.context.step_results[0]['tool'] == 'toolA'
    assert got.context.step_results[0]['success'] is True


def test_concurrent_access(temp_db):
    import threading, time
    repo = SQLiteTaskRepository(temp_db)
    errors = []
    def writer(i):
        try:
            rec = make_record()
            rec.id = f'task-{i}'
            repo.create(rec)
            rec.status = TaskStatus.PAUSED
            repo.update(rec)
        except Exception as e:
            errors.append(e)
    threads = [threading.Thread(target=writer, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    all_tasks = repo.list()
    assert len(all_tasks) == 10