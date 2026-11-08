from pathlib import Path

import pytest

from caliburn.task_store import InvalidTransition, MissingTask, TaskStore


def test_persist_and_transition(tmp_path: Path):
    path = str(tmp_path / "work.db")
    task = TaskStore(path).create("Do something")
    assert TaskStore(path).get(task.id).state == "QUEUED"
    store = TaskStore(path)
    assert store.transition(task.id, "RUNNING").state == "RUNNING"
    assert store.transition(task.id, "WAITING_APPROVAL").state == "WAITING_APPROVAL"
    assert store.transition(task.id, "RUNNING").state == "RUNNING"
    assert store.transition(task.id, "COMPLETED").state == "COMPLETED"
    with pytest.raises(InvalidTransition):
        store.transition(task.id, "RUNNING")


def test_no_unknown_task(tmp_path: Path):
    store = TaskStore(str(tmp_path / "work.db"))
    with pytest.raises(MissingTask):
        store.get("not-here")


def test_cancel_from_queued(tmp_path: Path):
    store = TaskStore(str(tmp_path / "work.db"))
    task = store.create("do something")
    assert store.transition(task.id, "CANCELLED").state == "CANCELLED"


def test_cannot_complete_unstarted_task(tmp_path: Path):
    store = TaskStore(str(tmp_path / "work.db"))
    task = store.create("do something")
    with pytest.raises(InvalidTransition):
        store.transition(task.id, "COMPLETED")
