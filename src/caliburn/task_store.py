"""Transactional SQLite metadata spike; not a durable asynchronous worker."""

import sqlite3
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from caliburn.contracts import TaskView

TRANSITIONS: dict[str, set[str]] = {
    "QUEUED": {"RUNNING", "CANCELLED"},
    "RUNNING": {"WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"},
    "WAITING_APPROVAL": {"RUNNING", "CANCELLED"},
    "COMPLETED": set(),
    "FAILED": set(),
    "CANCELLED": set(),
    "TIMED_OUT": set(),
}


class MissingTask(Exception):
    pass


class InvalidTransition(Exception):
    pass


class TaskStore:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    prompt TEXT NOT NULL,
                    state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path, timeout=5)

    def create(self, prompt: str) -> TaskView:
        task_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO tasks VALUES (?, ?, ?, ?, ?)",
                (task_id, prompt, "QUEUED", now, now),
            )
        return self.get(task_id)

    def get(self, task_id: str) -> TaskView:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT id, prompt, state, created_at, updated_at FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise MissingTask(task_id)
        return TaskView(
            id=row[0], prompt=row[1], state=row[2], created_at=row[3], updated_at=row[4]
        )

    def transition(self, task_id: str, new_state: str) -> TaskView:
        if new_state not in TRANSITIONS:
            raise InvalidTransition("Unknown task state")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT state FROM tasks WHERE id = ?", (task_id,)).fetchone()
            if row is None:
                raise MissingTask(task_id)
            old_state = row[0]
            if new_state not in TRANSITIONS[old_state]:
                raise InvalidTransition(f"Invalid transition: {old_state} -> {new_state}")
            connection.execute(
                "UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
                (new_state, datetime.now(UTC).isoformat(), task_id),
            )
        return self.get(task_id)


@lru_cache
def get_task_store(db_path: str) -> TaskStore:
    return TaskStore(db_path)
