"""Actual worker process exits after observing execution evidence, before checkpoint."""

import asyncio
import os

from test_factory_execution import ExecutionModel

from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker

store = Store(os.environ["CALIBURN_DATABASE_URL"])
original = store.commit


def crash(task_id, token, step_id, message, final=False):
    if message.get("role") == "tool" and message.get("name") == "capability_execute_tests":
        os._exit(73)
    return original(task_id, token, step_id, message, final)


store.commit = crash
asyncio.run(
    Worker(
        store,
        ExecutionModel(os.environ["CALIBURN_FACTORY_TEST_PLAN"]),
        lease_seconds=1,
        output_tokens=4096,
    ).run_once()
)
