"""Opt-in fixed-image Git data supervisor. Git image approval is separate."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from caliburn.config import get_settings
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.store import get_store
from caliburn.sandbox.contracts import GitData, Result
from caliburn.sandbox.control import DockerExecutor, SandboxFailure, Supervisor
from caliburn.sandbox.queue import WorkspaceQueue


class GitDockerExecutor(DockerExecutor):
    tools = ("repo_git_status",)

    def __init__(self, image_digest, *, timeout=20):
        super().__init__(image_digest, timeout=timeout)
        self.guard = None

    def bind_guard(self, guard):
        self.guard = guard

    async def before_dispatch(self, job):
        if self.guard is None or not await self.guard(job):
            raise SandboxFailure("git_admission_denied")

    async def execute(self, job):
        try:
            await self.before_dispatch(job)
        except SandboxFailure:
            return Result(ok=False, error="git_admission_denied")
        return await super().execute(job)

    def command(self, name, *, expires_at=None):
        command = super().command(name, expires_at=expires_at)
        command[-1] = "/opt/git_runner.py"
        return command

    def payload(self, job):
        return json.dumps(
            {
                "base": job["git_base"],
                "candidate": job["git_candidate"],
                "task_ref": job["task_id"],
                "baseline_sha256": job["git_baseline_sha256"],
                "candidate_sha256": job["git_candidate_sha256"],
            },
            ensure_ascii=False,
        ).encode()

    def validate(self, job, raw):
        result = Result.model_validate_json(raw)
        if not result.ok:
            return result
        root = Path(__file__).parent
        expected = hashlib.sha256(
            b"".join(
                (root / name).read_bytes()
                for name in ("git_runner.py", "git_workspace.py", "runner.py")
            )
        ).hexdigest()
        if result.isolation.get("runner_sha256") != expected:
            raise SandboxFailure("git_runner_revision_mismatch")
        data = GitData.model_validate(result.data)
        if (
            data.baseline_sha256 != job["git_baseline_sha256"]
            or data.candidate_sha256 != job["git_candidate_sha256"]
        ):
            raise SandboxFailure("git_source_changed")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Approved immutable local Git image")
    args = parser.parse_args()
    settings = get_settings()
    asyncio.run(
        Supervisor(
            WorkspaceQueue(get_store(settings.database_url)),
            GitDockerExecutor(args.image),
            secrets=platform_secrets(settings),
        ).serve()
    )


if __name__ == "__main__":
    main()
