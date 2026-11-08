"""Actual DB/worker/host Git; container transport explicitly opt-in and unverified until built."""

import asyncio
import hashlib
import json
import os

import pytest
from pydantic import ValidationError

from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import LostLease
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle, GitData, Operation, Result
from caliburn.sandbox.control import DockerExecutor, Supervisor
from caliburn.sandbox.git_control import GitDockerExecutor
from caliburn.sandbox.git_workspace import build_workspace
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue

IMAGE = "sha256:" + "a" * 64
FILES = {"calc.py": "def total(a,b): return a-b\n"}


class HostGitFixtureExecutor:
    """Fixture substitutes only Docker transport, never claims container isolation."""

    tools = ("repo_git_status",)

    def __init__(self, root):
        self.image = IMAGE
        self.root = root
        self.pending_creates = set()

    async def reap_expired(self):
        return []

    async def execute(self, job):
        directory = self.root / job["id"]
        directory.mkdir()
        metadata, patch = await asyncio.to_thread(
            build_workspace, directory, job["git_base"], job["git_candidate"], job["task_id"]
        )
        data = GitData(
            **metadata,
            baseline_sha256=job["git_baseline_sha256"],
            candidate_sha256=job["git_candidate_sha256"],
            diff=patch[:16384].decode(),
            diff_sha256=hashlib.sha256(patch).hexdigest(),
            diff_truncated=len(patch) > 16384,
            mode="scoped_snapshot_reconstruction",
            source_executed=False,
        )
        return Result(
            ok=True,
            data=data.model_dump(),
            isolation={"transport": "host-Git fixture, NOT container isolation"},
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("transport", ["host", "container"])
async def test_worker_git_consumer(durable, tmp_path, transport):
    data_image = os.getenv("CALIBURN_SANDBOX_TEST_IMAGE")
    if not data_image:
        pytest.skip("Actual data-runner image required")
    if transport == "container":
        image = os.getenv("CALIBURN_GIT_TEST_IMAGE")
        if not image:
            pytest.skip("Git image build/container qualification awaits explicit operator approval")
        executor = GitDockerExecutor(image)
    else:
        image, executor = IMAGE, HostGitFixtureExecutor(tmp_path)
    queue = WorkspaceQueue(durable)
    wid = queue.register(Bundle(files=FILES), propose_patch=True, git_image_digest=image)
    task = durable.submit(
        Submit(
            prompt="propose fix and inspect actual scoped Git diff",
            workspace_ref=wid,
            limits={"call_timeout_seconds": 40, "timeout_seconds": 120},
        )
    )

    class ModelFixture:
        async def complete(self, messages, tools):
            observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if not observations:
                name, arguments = (
                    "repo_patch",
                    {
                        "path": "calc.py",
                        "expected_sha256": hashlib.sha256(FILES["calc.py"].encode()).hexdigest(),
                        "old": "a-b",
                        "new": "a+b",
                    },
                )
            elif len(observations) == 1:
                name, arguments = (
                    "repo_git_status",
                    {"candidate_ref": observations[-1]["candidate_ref"]},
                )
            else:
                data = observations[-1]["data"]
                assert data["changed_files"] == ["calc.py"]
                assert "+def total(a,b): return a+b" in data["diff"]
                assert data["source_executed"] is False
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "Actual scoped Git checkout/diff observed; no source execution."
                            }
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": name,
                                    "function": {"name": name, "arguments": json.dumps(arguments)},
                                }
                            ]
                        }
                    }
                ]
            }

    serving = [
        asyncio.create_task(Supervisor(queue, implementation).serve())
        for implementation in (DockerExecutor(data_image), executor)
    ]
    try:
        await asyncio.wait_for(Worker(durable, ModelFixture()).run_once(), 60)
    finally:
        for process in serving:
            process.cancel()
        await asyncio.gather(*serving, return_exceptions=True)
    final = durable.get(task["id"])
    assert final["state"] == "COMPLETED", final["error"]
    assert (final["model_calls"], final["tool_calls"]) == (3, 2)


@pytest.mark.parametrize("action", ["wrong_image", "cancel", "revoke"])
def test_git_job_scope_image_and_fencing(durable, action):
    queue = WorkspaceQueue(durable)
    wid = queue.register(Bundle(files=FILES), git_image_digest=IMAGE)
    task = durable.submit(Submit(prompt="scoped Git baseline", workspace_ref=wid))
    lease = durable.claim("git-boundary-fixture", 30)
    step = durable.prepare(task["id"], lease["lease_token"], "TOOL", {})
    queue.request(
        task["id"],
        lease["lease_token"],
        step["id"],
        Operation(tool="repo_git_status", arguments={}),
    )
    assert queue.claim(IMAGE) is None  # Existing data supervisor cannot claim this operation.
    assert queue.claim("sha256:" + "0" * 64, tools=("repo_git_status",)) is None
    job = queue.claim(IMAGE, tools=("repo_git_status",))
    assert job
    if action == "cancel":
        durable.control(task["id"], "cancel")
    elif action == "revoke":
        queue.revoke(wid)
    else:
        job = dict(job, image_digest="sha256:" + "0" * 64)
    assert not queue.heartbeat(job)
    with pytest.raises((LostLease, WorkspaceDenied)):
        queue.finish(job, Result(ok=False, error="fixture stale result"))


def test_git_permission_is_not_implicit_and_arguments_cannot_grant_it(durable):
    queue = WorkspaceQueue(durable)
    wid = queue.register(Bundle(files=FILES))
    task = durable.submit(Submit(prompt="read-only fixture", workspace_ref=wid))
    assert "repo_git_status" not in task["policy"]["tools"]
    lease = durable.claim("not-granted", 30)
    step = durable.prepare(task["id"], lease["lease_token"], "TOOL", {})
    with pytest.raises(WorkspaceDenied):
        queue.request(
            task["id"],
            lease["lease_token"],
            step["id"],
            Operation(tool="repo_git_status", arguments={}),
        )
    with pytest.raises(ValidationError):
        Operation(
            tool="repo_git_status", arguments={"command": "id", "image": IMAGE, "approved": True}
        )


@pytest.mark.asyncio
async def test_git_executor_requires_live_admission():
    result = await GitDockerExecutor(IMAGE).execute({})
    assert not result.ok and result.error == "git_admission_denied"


@pytest.fixture
def git_image():
    image = os.getenv("CALIBURN_GIT_TEST_IMAGE")
    if not image:
        pytest.skip("Git image/container checks await explicit development build approval")
    return image


def isolated_job():
    base = Bundle(
        files={
            "calc.py": "raise RuntimeError('must never import')\n",
            ".gitattributes": "* text eol=crlf filter=poison working-tree-encoding=UTF-16 diff=poison\n",
        }
    )
    target = Bundle(files={**base.files, "calc.py": "raise RuntimeError('still inert')\n"})
    return {
        "task_id": "f" * 36,
        "git_base": base.files,
        "git_candidate": target.files,
        "git_baseline_sha256": base.digest(),
        "git_candidate_sha256": target.digest(),
    }


@pytest.mark.asyncio
async def test_actual_git_image_kernel_and_inert_attributes(git_image):
    executor = GitDockerExecutor(git_image)

    async def fixture_admission(_job):
        return True

    executor.bind_guard(fixture_admission)
    result = await executor.execute(isolated_job())
    assert result.ok, result.error
    assert result.data["source_executed"] is False
    assert result.data["changed_files"] == ["calc.py"]
    assert "still inert" in result.data["diff"]
    assert result.data["git_version"].startswith("git version 2.47.3")
    isolation = result.isolation
    assert isolation["uid"] == 10001 and isolation["root_readonly"]
    assert isolation["interfaces"] == ["lo"] and not isolation["docker_socket"]
    assert isolation["CapEff"] == "0000000000000000" and isolation["NoNewPrivs"] == "1"
    assert isolation["Seccomp"] == "2" and isolation["memory_max"] == "134217728"
    assert isolation["pids_max"] == "32"


@pytest.mark.asyncio
async def test_actual_git_image_timeout_and_cancel_remove_container(git_image):
    async def fixture_admission(_job):
        return True

    timed = GitDockerExecutor(git_image, timeout=0.001)
    timed.bind_guard(fixture_admission)
    result = await timed.execute(isolated_job())
    assert not result.ok and result.error == "sandbox_timeout"
    ready = asyncio.Event()
    names = []

    class Observed(GitDockerExecutor):
        def command(self, name, **kwargs):
            names.append(name)
            return super().command(name, **kwargs)

        def payload(self, job):
            ready.set()
            return super().payload(job)

    executor = Observed(git_image)
    executor.bind_guard(fixture_admission)
    execution = asyncio.create_task(executor.execute(isolated_job()))
    await asyncio.wait_for(ready.wait(), 10)
    execution.cancel()
    with pytest.raises(asyncio.CancelledError):
        await execution
    for name in names:
        inspect = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert await inspect.wait() != 0
