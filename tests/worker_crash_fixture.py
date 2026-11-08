"""Maintained crash harness, not agent-generated executable source."""

import asyncio
import os

from caliburn.config import get_settings
from caliburn.llm import FixtureModel
from caliburn.runtime.store import Store
from caliburn.runtime.worker import Worker


class CrashStore(Store):
    def commit(self, task_id, token, step_id, message, final=False):
        if message["role"] == "tool":
            os._exit(73)
        return super().commit(task_id, token, step_id, message, final)


if __name__ == "__main__":
    asyncio.run(
        Worker(
            # Reach the deliberate crash point even under a loaded Windows/Docker host.
            # The parent test waits for actual DB-clock lease expiry after exit73.
            CrashStore(get_settings().database_url),
            FixtureModel(),
            lease_seconds=3,
        ).run_once()
    )
