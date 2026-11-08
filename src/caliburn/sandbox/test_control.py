"""Trusted-host reviewed-test supervisor. Opt-in; no Docker in agent processes."""

import argparse
import asyncio
import hashlib
import json
from pathlib import Path

from caliburn.config import get_settings
from caliburn.runtime.redaction import platform_secrets
from caliburn.runtime.store import get_store
from caliburn.sandbox.contracts import Result, TestData, TestRun
from caliburn.sandbox.control import DockerExecutor, SandboxFailure, Supervisor
from caliburn.sandbox.queue import WorkspaceQueue


class ReviewedTestExecutor(DockerExecutor):
    tools = ("repo_test",)

    def __init__(self, image_digest, *, timeout=20, guard=None):
        super().__init__(image_digest, timeout=timeout)
        self.guard = guard

    def bind_guard(self, guard):
        self.guard = guard

    async def before_dispatch(self, job):
        if self.guard is None or not await self.guard(job):
            raise SandboxFailure("test_authorization_denied")

    def command(self, name, *, expires_at=None):
        command = super().command(name, expires_at=expires_at)
        command[-1] = "/opt/test_runner.py"
        return command

    def payload(self, job):
        return json.dumps(
            {
                "files": job["variant_files"],
                "source_sha256": job["variant_sha256"],
                "plan": job["plan_files"],
                "plan_sha256": job["binding"]["plan_sha256"],
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
                for name in ("test_runner.py", "runner.py", "test_check.py")
            )
        ).hexdigest()
        if result.isolation.get("runner_sha256") != expected:
            raise SandboxFailure("test_runner_revision_mismatch")
        result.data = TestRun.model_validate(result.data).model_dump()
        if (
            result.data["source_sha256"] != job["variant_sha256"]
            or result.data["plan_sha256"] != job["binding"]["plan_sha256"]
        ):
            raise SandboxFailure("test_artifact_mismatch")
        return result

    async def execute(self, job):
        observations, isolation = {}, {}
        for variant, key in (("baseline", "base"), ("candidate", "candidate")):
            try:
                await self.before_dispatch(job)
            except SandboxFailure:
                return Result(ok=False, error="test_authorization_denied")
            # Each run gets its own container, tmpfs and independently checked image.
            result = await super().execute(
                {
                    **job,
                    "variant_files": job[key + "_files"],
                    "variant_sha256": job["binding"][key + "_sha256"],
                }
            )
            if not result.ok:
                return result
            observations[variant] = result.data
            isolation[variant] = result.isolation
        return Result(
            ok=True,
            data=TestData(
                request_ref=job["request_ref"],
                binding_sha256=job["binding_sha256"],
                image_digest=self.image,
                baseline=TestRun(**observations["baseline"]),
                candidate=TestRun(**observations["candidate"]),
                source_executed=True,
                production_approved=False,
            ).model_dump(),
            isolation=isolation,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Reviewed immutable local test image ID")
    parser.add_argument("--reap-only", action="store_true")
    args = parser.parse_args()
    executor = ReviewedTestExecutor(args.image)
    if args.reap_only:
        print(json.dumps({"removed": asyncio.run(executor.reap_expired())}))
        return
    settings = get_settings()
    asyncio.run(
        Supervisor(
            WorkspaceQueue(get_store(settings.database_url)),
            executor,
            secrets=platform_secrets(settings),
        ).serve()
    )


if __name__ == "__main__":
    main()
