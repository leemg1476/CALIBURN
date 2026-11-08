"""Trusted host control plane only. Never run in or grant Docker to an agent container."""

import argparse
import asyncio
import contextlib
import hashlib
import json
import math
import re
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy.exc import SQLAlchemyError

from caliburn.config import get_settings
from caliburn.runtime.redaction import contains_secret, platform_secrets
from caliburn.runtime.store import LostLease, get_store
from caliburn.sandbox.contracts import Operation, Result, validate_result
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue


class SandboxFailure(Exception):
    pass


class DockerExecutor:
    tools = ("repo_list", "repo_read", "repo_search", "repo_patch")

    def __init__(self, image_digest, *, timeout=20):
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
            raise ValueError("Sandbox image must be an immutable local SHA256 image ID")
        self.image = image_digest
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise ValueError("Sandbox timeout must be finite and between 0 and 60 seconds")
        self.timeout = timeout
        self.pending_creates = set()

    def command(self, name, *, expires_at=None):
        if not re.fullmatch(r"caliburn-sbx-[a-f0-9]{32}", name):
            raise ValueError("Invalid container name")
        return [
            "docker",
            "create",
            "--rm",
            "--interactive",
            "--label=caliburn.sandbox=managed-v2",
            "--label=caliburn.sandbox.expires-at="
            + str(
                expires_at if expires_at is not None else time.time() + max(25, self.timeout) + 15
            ),
            "--pull=never",
            "--name",
            name,
            "--network=none",
            "--read-only",
            "--user=10001:10001",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=0.5",
            "--pids-limit=32",
            "--ulimit=nofile=128:128",
            "--ulimit=nproc=32:32",
            "--tmpfs=/work:rw,noexec,nosuid,nodev,size=16m,uid=10001,gid=10001,mode=0700",
            "--workdir=/work",
            "--log-driver=none",
            "--no-healthcheck",
            "--init",
            "--entrypoint=python",
            self.image,
            "-I",
            "-B",
            "/opt/runner.py",
        ]

    async def remove(self, name):
        if not re.fullmatch(r"caliburn-sbx-[a-f0-9]{32}", name):
            raise ValueError("Invalid cleanup name")
        cleanup = await asyncio.create_subprocess_exec(
            "docker",
            "rm",
            "--force",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            await asyncio.wait_for(cleanup.wait(), 5)
        except TimeoutError:
            cleanup.kill()
            await cleanup.wait()
            return False
        return cleanup.returncode == 0

    async def create(self, name, abandoned):
        process = None
        try:
            async with asyncio.timeout(10):
                process = await asyncio.create_subprocess_exec(
                    *self.command(name),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await process.communicate()
            return process.returncode
        finally:
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()
            # This coroutine owns the entire spawn/daemon-create handshake, including
            # the period before create_subprocess_exec returns a process handle.
            if abandoned.is_set():
                await self.remove(name)

    async def reap_expired(self):
        listing = await asyncio.create_subprocess_exec(
            "docker",
            "ps",
            "--all",
            "--filter",
            "label=caliburn.sandbox=managed-v2",
            "--format",
            "{{.ID}}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        raw, _ = await listing.communicate()
        if listing.returncode:
            raise SandboxFailure("sandbox_inventory_failed")
        removed = []
        for cid in raw.decode().splitlines()[:128]:
            if not re.fullmatch(r"[a-f0-9]{12,64}", cid):
                continue
            check = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                cid,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            data, _ = await check.communicate()
            if check.returncode:
                continue
            container = json.loads(data)[0]
            name = container["Name"].removeprefix("/")
            labels = container["Config"].get("Labels") or {}
            try:
                expiry = float(labels.get("caliburn.sandbox.expires-at", "nan"))
            except (ValueError, TypeError):
                continue
            host = container["HostConfig"]
            # Never address unlabeled/legacy/user containers, arbitrary names,
            # unexpired jobs or instances carrying host data.
            if (
                labels.get("caliburn.sandbox") != "managed-v2"
                or not re.fullmatch(r"caliburn-sbx-[a-f0-9]{32}", name)
                or not math.isfinite(expiry)
                or expiry > time.time()
                or not host["ReadonlyRootfs"]
                or host["NetworkMode"] != "none"
                or host.get("Binds")
                or host.get("Privileged")
                or any(
                    m["Type"] != "tmpfs" or m["Destination"] != "/work"
                    for m in container.get("Mounts", [])
                )
            ):
                continue
            if await self.remove(name):
                removed.append(name)
        return removed

    async def attest(self, name):
        for _ in range(100):
            check = await asyncio.create_subprocess_exec(
                "docker",
                "inspect",
                name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            output, _ = await check.communicate()
            if check.returncode == 0:
                container = json.loads(output)[0]
                host = container["HostConfig"]
                if (
                    container["Image"] != self.image
                    or host["NetworkMode"] != "none"
                    or not host["ReadonlyRootfs"]
                    or container["Config"]["User"] != "10001:10001"
                    or host["Privileged"]
                    or host.get("Binds")
                    or host.get("CapAdd")
                    or "ALL" not in host["CapDrop"]
                    or host["Memory"] != 134217728
                    or host["PidsLimit"] != 32
                    or host["NanoCpus"] != 500000000
                    or host["MemorySwap"] != 134217728
                    or not any(x.startswith("no-new-privileges") for x in host["SecurityOpt"])
                    or set(host["Tmpfs"]) != {"/work"}
                    or any(
                        mount["Type"] != "tmpfs" or mount["Destination"] != "/work"
                        for mount in container.get("Mounts", [])
                    )
                ):
                    raise SandboxFailure("sandbox_isolation_mismatch")
                return
            await asyncio.sleep(0.05)
        raise SandboxFailure("sandbox_startup_failed")

    async def execute(self, job):
        name = "caliburn-sbx-" + uuid4().hex
        process = creation = None
        abandoned = asyncio.Event()
        try:
            async with asyncio.timeout(self.timeout):
                creation = asyncio.create_task(self.create(name, abandoned))
                self.pending_creates.add(creation)
                creation.add_done_callback(self.pending_creates.discard)
                # Shield the whole spawn handshake, not only communicate().
                status = await asyncio.shield(creation)
                if status:
                    raise SandboxFailure("sandbox_create_failed")
                await self.attest(name)
                await self.before_dispatch(job)
                process = await asyncio.create_subprocess_exec(
                    "docker",
                    "start",
                    "--attach",
                    "--interactive",
                    name,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                payload = self.payload(job)
                process.stdin.write(payload)
                await process.stdin.drain()
                process.stdin.close()
                chunks = []
                size = 0
                while chunk := await process.stdout.read(16384):
                    size += len(chunk)
                    if size > 131072:
                        raise SandboxFailure("sandbox_output_limit")
                    chunks.append(chunk)
                await process.wait()
                if process.returncode:
                    raise SandboxFailure("sandbox_process_failed")
                return self.validate(job, b"".join(chunks))
        except TimeoutError:
            return Result(ok=False, error="sandbox_timeout")
        except (ValueError, OSError, BrokenPipeError, SandboxFailure):
            return Result(ok=False, error="sandbox_execution_failed")
        finally:
            abandoned.set()
            if creation is not None and not creation.done():
                with contextlib.suppress(TimeoutError, OSError):
                    await asyncio.wait_for(asyncio.shield(creation), 12)
            # Late creation also owns its cleanup; the persisted expiry is the
            # restart backstop if the entire supervisor is killed.
            await self.remove(name)
            if process is not None and process.returncode is None:
                process.kill()
                await process.wait()

    def payload(self, job):
        return json.dumps(
            {"files": job["files"], "digest": job["digest"], "operation": job["operation"]},
            ensure_ascii=False,
        ).encode()

    async def before_dispatch(self, job):
        """Final admission hook after independent container inspection, before source delivery."""

    def validate(self, job, raw):
        result = Result.model_validate_json(raw)
        expected = hashlib.sha256(Path(__file__).with_name("runner.py").read_bytes()).hexdigest()
        if result.isolation.get("runner_sha256") != expected:
            raise SandboxFailure("sandbox_runner_revision_mismatch")
        return validate_result(Operation.model_validate(job["operation"]), result)


class Supervisor:
    def __init__(self, queue, executor, *, secrets=()):
        self.queue, self.executor = queue, executor
        self.secrets = secrets
        if hasattr(executor, "bind_guard"):
            executor.bind_guard(self._authorize)

    async def _authorize(self, job):
        return await asyncio.to_thread(self.queue.heartbeat, job)

    async def _watch(self, job, execution):
        while True:
            await asyncio.sleep(0.2)
            try:
                alive = await asyncio.to_thread(self.queue.heartbeat, job)
            except SQLAlchemyError:
                alive = False
            if not alive:
                execution.cancel()
                return

    async def run_once(self):
        job = await asyncio.to_thread(
            self.queue.claim,
            self.executor.image,
            tools=getattr(self.executor, "tools", DockerExecutor.tools),
        )
        if job is None:
            return False
        if contains_secret(job, self.secrets):
            await asyncio.to_thread(
                self.queue.finish, job, Result(ok=False, error="platform_secret_denied")
            )
            return True
        execution = asyncio.create_task(self.executor.execute(job))
        watcher = asyncio.create_task(self._watch(job, execution))
        try:
            result = await execution
            if contains_secret(result.model_dump(), self.secrets):
                result = Result(ok=False, error="platform_secret_denied")
            await asyncio.to_thread(self.queue.finish, job, result)
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise
        except (LostLease, WorkspaceDenied):
            pass
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        return True

    async def serve(self):
        last_reap = float("-inf")
        try:
            while True:
                try:
                    if time.monotonic() - last_reap >= 5:
                        await self.executor.reap_expired()
                        last_reap = time.monotonic()
                    if not await self.run_once():
                        await asyncio.sleep(0.1)
                except (SQLAlchemyError, OSError, SandboxFailure):
                    await asyncio.sleep(1)
        finally:
            if self.executor.pending_creates:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.gather(*self.executor.pending_creates, return_exceptions=True), 12
                    )


def main():
    parser = argparse.ArgumentParser(
        description="Trusted operator supervisor; no agent Docker access"
    )
    parser.add_argument("--image", required=True, help="Reviewed immutable local sha256 image ID")
    parser.add_argument(
        "--reap-only", action="store_true", help="Remove only expired managed-v2 sandboxes"
    )
    args = parser.parse_args()
    if args.reap_only:
        print(json.dumps({"removed": asyncio.run(DockerExecutor(args.image).reap_expired())}))
        return
    settings = get_settings()
    asyncio.run(
        Supervisor(
            WorkspaceQueue(get_store(settings.database_url)),
            DockerExecutor(args.image),
            secrets=platform_secrets(settings),
        ).serve()
    )


if __name__ == "__main__":
    main()
