"""Task repository abstraction with SQLite backend."""
from __future__ import annotations
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Dict, List, Optional

from .models import TaskRecord, TaskStatus


class TaskRepository:
    """Interface for task persistence."""

    def create(self, record: TaskRecord) -> str:
        raise NotImplementedError

    def get(self, task_id: str) -> Optional[TaskRecord]:
        raise NotImplementedError

    def update(self, record: TaskRecord) -> None:
        raise NotImplementedError

    def list(self, status: Optional[TaskStatus] = None) -> List[TaskRecord]:
        raise NotImplementedError

    def claim_and_recover_task(self, record: TaskRecord, expected_updated_at: Optional[str] = None) -> bool:
        raise NotImplementedError


class SQLiteTaskRepository(TaskRepository):
    """SQLite implementation of TaskRepository."""

    def __init__(self, db_path: str = "nova_tasks.db"):
        self._db_path = db_path
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    plan TEXT NOT NULL,
                    context TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    current_step INTEGER NOT NULL,
                    max_steps INTEGER,
                    wall_clock_timeout_seconds INTEGER,
                    title TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    priority TEXT DEFAULT 'normal',
                    steps TEXT DEFAULT '[]',
                    started_at TEXT,
                    completed_at TEXT,
                    error TEXT,
                    metadata TEXT DEFAULT '{}'
                )
                """
            )
            # Safe non-destructive schema migration for existing databases
            cursor = conn.execute("PRAGMA table_info(tasks)")
            existing_cols = {col[1] for col in cursor.fetchall()}
            new_cols = {
                "title": "TEXT DEFAULT ''",
                "description": "TEXT DEFAULT ''",
                "priority": "TEXT DEFAULT 'normal'",
                "steps": "TEXT DEFAULT '[]'",
                "started_at": "TEXT",
                "completed_at": "TEXT",
                "error": "TEXT",
                "metadata": "TEXT DEFAULT '{}'",
            }
            for col, col_def in new_cols.items():
                if col not in existing_cols:
                    conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {col_def}")
            conn.commit()

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _row_to_record(self, row: sqlite3.Row) -> TaskRecord:
        plan_dict = json.loads(row["plan"])
        context_dict = json.loads(row["context"])
        from .models import ExecutionPlan, ExecutionContext, TaskStep, TaskPriority, ActionStatus
        plan = ExecutionPlan(**plan_dict)
        context = ExecutionContext(**context_dict)
        row_keys = row.keys()

        title = row["title"] if "title" in row_keys and row["title"] is not None else ""
        description = row["description"] if "description" in row_keys and row["description"] is not None else ""
        
        priority_val = row["priority"] if "priority" in row_keys and row["priority"] is not None else "normal"
        try:
            priority = TaskPriority(priority_val)
        except Exception:
            priority = TaskPriority.NORMAL

        steps_raw = row["steps"] if "steps" in row_keys and row["steps"] is not None else "[]"
        try:
            steps_data = json.loads(steps_raw)
            steps = [TaskStep(**s) for s in steps_data]
        except Exception:
            steps = []

        # Fallback to plan.steps for legacy records
        if not steps and plan.steps:
            steps = [TaskStep.from_tool_action(action, step_index=i) for i, action in enumerate(plan.steps)]
            for res in context.step_results:
                s_idx = res.get("step")
                if s_idx is not None and 0 <= s_idx < len(steps):
                    if res.get("success"):
                        steps[s_idx].status = ActionStatus.SUCCESS
                        steps[s_idx].result = res.get("result")
                    else:
                        steps[s_idx].status = ActionStatus.FAILED
                        steps[s_idx].error = str(res.get("result") or "")

        started_at = datetime.fromisoformat(row["started_at"]) if "started_at" in row_keys and row["started_at"] else None
        completed_at = datetime.fromisoformat(row["completed_at"]) if "completed_at" in row_keys and row["completed_at"] else None
        error = row["error"] if "error" in row_keys else None

        meta_raw = row["metadata"] if "metadata" in row_keys and row["metadata"] is not None else "{}"
        try:
            metadata = json.loads(meta_raw)
        except Exception:
            metadata = {}
        if not metadata and context.metadata:
            metadata = context.metadata

        return TaskRecord(
            id=row["id"],
            plan=plan,
            context=context,
            status=TaskStatus(row["status"]),
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            current_step=row["current_step"],
            max_steps=row["max_steps"],
            wall_clock_timeout_seconds=row["wall_clock_timeout_seconds"],
            title=title,
            description=description,
            priority=priority,
            steps=steps,
            started_at=started_at,
            completed_at=completed_at,
            error=error,
            metadata=metadata,
        )

    def create(self, record: TaskRecord) -> str:
        with self._lock, self._connect() as conn:
            plan_json = record.plan.model_dump_json()
            context_json = record.context.model_dump_json()
            steps_json = json.dumps([s.model_dump(mode="json") for s in record.steps])
            metadata_json = json.dumps(record.metadata)
            conn.execute(
                """
                INSERT INTO tasks (
                    id, plan, context, status, created_at, updated_at,
                    current_step, max_steps, wall_clock_timeout_seconds,
                    title, description, priority, steps, started_at, completed_at, error, metadata
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    plan_json,
                    context_json,
                    record.status.value,
                    record.created_at.isoformat(),
                    record.updated_at.isoformat(),
                    record.current_step,
                    record.max_steps,
                    record.wall_clock_timeout_seconds,
                    record.title,
                    record.description,
                    record.priority.value,
                    steps_json,
                    record.started_at.isoformat() if record.started_at else None,
                    record.completed_at.isoformat() if record.completed_at else None,
                    record.error,
                    metadata_json,
                ),
            )
            conn.commit()
        return record.id

    def get(self, task_id: str) -> Optional[TaskRecord]:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)

    def update(self, record: TaskRecord) -> None:
        with self._lock, self._connect() as conn:
            plan_json = record.plan.model_dump_json()
            context_json = record.context.model_dump_json()
            steps_json = json.dumps([s.model_dump(mode="json") for s in record.steps])
            metadata_json = json.dumps(record.metadata)
            conn.execute(
                """
                UPDATE tasks SET
                    plan = ?, context = ?, status = ?, updated_at = ?, current_step = ?,
                    max_steps = ?, wall_clock_timeout_seconds = ?,
                    title = ?, description = ?, priority = ?, steps = ?,
                    started_at = ?, completed_at = ?, error = ?, metadata = ?
                WHERE id = ?
                """,
                (
                    plan_json,
                    context_json,
                    record.status.value,
                    record.updated_at.isoformat(),
                    record.current_step,
                    record.max_steps,
                    record.wall_clock_timeout_seconds,
                    record.title,
                    record.description,
                    record.priority.value,
                    steps_json,
                    record.started_at.isoformat() if record.started_at else None,
                    record.completed_at.isoformat() if record.completed_at else None,
                    record.error,
                    metadata_json,
                    record.id,
                ),
            )
            conn.commit()

    def list(self, status: Optional[TaskStatus] = None) -> List[TaskRecord]:
        with self._lock, self._connect() as conn:
            if status is None:
                rows = conn.execute("SELECT * FROM tasks").fetchall()
            else:
                rows = conn.execute("SELECT * FROM tasks WHERE status = ?", (status.value,)).fetchall()
            return [self._row_to_record(row) for row in rows]

    def claim_and_recover_task(self, record: TaskRecord, expected_updated_at: Optional[str] = None) -> bool:
        """
        Atomically claim and recover an orphaned task from RUNNING to PAUSED,
        simultaneously persisting its steps (with any in-flight step marked INTERRUPTED).
        Uses CAS (WHERE id = ? AND status = 'running' [AND updated_at = ?]) inside a transaction.
        Returns True if this instance won the claim and recovered the task, False otherwise.
        """
        with self._lock, self._connect() as conn:
            plan_json = record.plan.model_dump_json()
            context_json = record.context.model_dump_json()
            steps_json = json.dumps([s.model_dump(mode="json") for s in record.steps])
            metadata_json = json.dumps(record.metadata)
            try:
                conn.execute("BEGIN IMMEDIATE")
                if expected_updated_at is not None:
                    exp_str = (
                        expected_updated_at.isoformat()
                        if hasattr(expected_updated_at, "isoformat")
                        else str(expected_updated_at)
                    )
                    query = """
                        UPDATE tasks SET
                            plan = ?, context = ?, status = ?, updated_at = ?, current_step = ?,
                            max_steps = ?, wall_clock_timeout_seconds = ?,
                            title = ?, description = ?, priority = ?, steps = ?,
                            started_at = ?, completed_at = ?, error = ?, metadata = ?
                        WHERE id = ? AND status = 'running' AND updated_at = ?
                    """
                    params = (
                        plan_json,
                        context_json,
                        record.status.value,
                        record.updated_at.isoformat(),
                        record.current_step,
                        record.max_steps,
                        record.wall_clock_timeout_seconds,
                        record.title,
                        record.description,
                        record.priority.value,
                        steps_json,
                        record.started_at.isoformat() if record.started_at else None,
                        record.completed_at.isoformat() if record.completed_at else None,
                        record.error,
                        metadata_json,
                        record.id,
                        exp_str,
                    )
                else:
                    query = """
                        UPDATE tasks SET
                            plan = ?, context = ?, status = ?, updated_at = ?, current_step = ?,
                            max_steps = ?, wall_clock_timeout_seconds = ?,
                            title = ?, description = ?, priority = ?, steps = ?,
                            started_at = ?, completed_at = ?, error = ?, metadata = ?
                        WHERE id = ? AND status = 'running'
                    """
                    params = (
                        plan_json,
                        context_json,
                        record.status.value,
                        record.updated_at.isoformat(),
                        record.current_step,
                        record.max_steps,
                        record.wall_clock_timeout_seconds,
                        record.title,
                        record.description,
                        record.priority.value,
                        steps_json,
                        record.started_at.isoformat() if record.started_at else None,
                        record.completed_at.isoformat() if record.completed_at else None,
                        record.error,
                        metadata_json,
                        record.id,
                    )
                cursor = conn.execute(query, params)
                rows_affected = cursor.rowcount
                if rows_affected == 1:
                    conn.commit()
                    return True
                else:
                    conn.rollback()
                    return False
            except Exception:
                conn.rollback()
                raise



# Default repository instance
_default_repository: Optional[TaskRepository] = None


def get_task_repository(db_path: str = "nova_tasks.db") -> TaskRepository:
    global _default_repository
    if _default_repository is None:
        _default_repository = SQLiteTaskRepository(db_path)
    return _default_repository