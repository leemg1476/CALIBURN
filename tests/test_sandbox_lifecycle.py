"""Real Docker lifecycle regressions; deliberately delay the create handshake."""

import asyncio
import json
import os
import time
from uuid import uuid4

import pytest

from caliburn.sandbox.contracts import Bundle, Operation
from caliburn.sandbox.control import DockerExecutor


@pytest.fixture
def image():
    value = os.getenv("CALIBURN_SANDBOX_TEST_IMAGE")
    if not value:
        pytest.skip("Set CALIBURN_SANDBOX_TEST_IMAGE for real lifecycle tests")
    return value


async def docker(*args):
    p = await asyncio.create_subprocess_exec(
        "docker", *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
    )
    output, _ = await p.communicate()
    return p.returncode, output


def job():
    bundle = Bundle(files={"calc.py": 'raise RuntimeError("source is inert")\n'})
    return {
        "files": bundle.files,
        "digest": bundle.digest(),
        "operation": Operation(tool="repo_list", arguments={}).model_dump(),
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "timeout"])
async def test_late_daemon_create_is_owned_and_removed(image, action):
    entered = asyncio.Event()
    names = []

    class DelayedExecutor(DockerExecutor):
        async def create(self, name, abandoned):
            names.append(name)
            entered.set()
            # The caller is cancelled/times out before a process handle is returned.
            await asyncio.sleep(0.05)
            return await super().create(name, abandoned)

    executor = DelayedExecutor(image, timeout=0.001 if action == "timeout" else 20)
    execution = asyncio.create_task(executor.execute(job()))
    await entered.wait()
    if action == "cancel":
        execution.cancel()
        with pytest.raises(asyncio.CancelledError):
            await execution
    else:
        result = await execution
        assert result.error == "sandbox_timeout"
    await asyncio.sleep(0.1)
    assert len(names) == 1
    status, _ = await docker("inspect", names[0])
    assert status != 0, "late-created container must not remain after cleanup returned"
    assert not executor.pending_creates


@pytest.mark.asyncio
async def test_restart_reaper_only_removes_expired_owned_instances(image):
    executor = DockerExecutor(image)
    expired = "caliburn-sbx-" + uuid4().hex
    active = "caliburn-sbx-" + uuid4().hex
    foreign = "caliburn-user-fixture-" + uuid4().hex
    bad_expiry = "caliburn-sbx-" + uuid4().hex
    created = []
    try:
        for name, expiry in [
            (expired, time.time() - 1),
            (active, time.time() + 120),
            (foreign, time.time() - 1),
            (bad_expiry, "not-an-epoch"),
        ]:
            # Foreign name is created explicitly by this test, never through executor.
            command = executor.command(
                name if name != foreign else "caliburn-sbx-" + uuid4().hex, expires_at=expiry
            )
            if name == foreign:
                command[command.index("--name") + 1] = foreign
            status, _ = await docker(*command[1:])
            assert status == 0
            created.append(name)
        removed = await DockerExecutor(image).reap_expired()  # fresh controller instance
        assert expired in removed
        assert active not in removed and foreign not in removed and bad_expiry not in removed
        for name in [active, foreign, bad_expiry]:
            status, _ = await docker("inspect", name)
            assert status == 0
    finally:
        for name in created:
            await docker("rm", "--force", name)


@pytest.mark.asyncio
async def test_lease_label_persists_before_container_start(image):
    executor = DockerExecutor(image)
    name = "caliburn-sbx-" + uuid4().hex
    try:
        status, _ = await docker(*executor.command(name)[1:])
        assert status == 0
        _, raw = await docker("inspect", name)
        container = json.loads(raw)[0]
        labels = container["Config"]["Labels"]
        assert container["State"]["Status"] == "created"
        assert labels["caliburn.sandbox"] == "managed-v2"
        assert time.time() < float(labels["caliburn.sandbox.expires-at"]) < time.time() + 50
        assert container["HostConfig"]["ReadonlyRootfs"]
        assert not container["Mounts"] or all(m["Type"] == "tmpfs" for m in container["Mounts"])
    finally:
        await executor.remove(name)


@pytest.mark.asyncio
async def test_cancel_between_process_spawn_and_handle_return(image, monkeypatch):
    import sys
    from pathlib import Path

    original = asyncio.create_subprocess_exec
    spawned = asyncio.Event()
    names = []

    async def delayed_handle(*command, **options):
        if command[:2] == ("docker", "create"):
            names.append(command[command.index("--name") + 1])
            process = await original(
                sys.executable,
                str(Path(__file__).with_name("delayed_docker_create.py")),
                *command,
                **options,
            )
            spawned.set()
            # A process is alive but the caller has no assigned handle yet.
            await asyncio.sleep(0.05)
            return process
        return await original(*command, **options)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", delayed_handle)
    executor = DockerExecutor(image)
    execution = asyncio.create_task(executor.execute(job()))
    await spawned.wait()
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    await asyncio.sleep(0.3)
    try:
        status, _ = await docker("inspect", names[0])
        assert status != 0, "cancelled creation must own cleanup after its delayed daemon mutation"
    finally:
        await executor.remove(names[0])
