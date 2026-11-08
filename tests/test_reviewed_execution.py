"""Real reviewed stdlib tests; inference/reviewer are explicitly synthetic fixtures."""

import asyncio
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, update
from test_review import PATCH, SOURCE, waiting

from caliburn.policy.review import ReviewPolicy
from caliburn.runtime.contracts import Submit
from caliburn.runtime.schema import tasks
from caliburn.runtime.store import LostLease
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle, Operation, Result
from caliburn.sandbox.control import DockerExecutor, Supervisor
from caliburn.sandbox.queue import WorkspaceDenied, WorkspaceQueue
from caliburn.sandbox.schema import jobs
from caliburn.sandbox.test_control import ReviewedTestExecutor

PLAN = {
    "test_calc.py": """import unittest
from calc import total

class Arithmetic(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(total(2, 3), 5)
        self.assertEqual(total(-1, 1), 0)
"""
}


@pytest.fixture
def test_image():
    image = os.getenv("CALIBURN_REVIEWED_TEST_IMAGE")
    if not image:
        pytest.skip("Set CALIBURN_REVIEWED_TEST_IMAGE for actual reviewed-test containers")
    return image


def proposal(durable, image, plan=None):
    queue = WorkspaceQueue(durable)
    wid = queue.register(
        Bundle(files={"calc.py": SOURCE}),
        propose_patch=True,
        request_review=True,
        execute_reviewed_tests=True,
    )
    pid = ReviewPolicy(durable).register_plan(wid, plan or PLAN, image)
    task = durable.submit(
        Submit(
            prompt="fix and validate arithmetic with reviewed tests",
            workspace_ref=wid,
            limits={"call_timeout_seconds": 40, "timeout_seconds": 120},
        )
    )
    return queue, pid, task


class ModelFixture:
    def __init__(self, pid):
        self.pid = pid

    async def complete(self, messages, tools):
        observations = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        if not observations:
            name, args = "repo_patch", PATCH
        elif len(observations) == 1:
            name, args = (
                "repo_request_review",
                {"candidate_ref": observations[-1]["candidate_ref"], "plan_ref": self.pid},
            )
        elif len(observations) == 2:
            name, args = "repo_test", {"request_ref": observations[-1]["data"]["request_ref"]}
        else:
            data = observations[-1]["data"]
            assert data["baseline"]["status"] == "FAILED"
            assert data["candidate"]["status"] == "PASSED"
            assert data["production_approved"] is False
            return {
                "choices": [
                    {
                        "message": {
                            "content": "Baseline failed; candidate passed the independently registered tests."
                        }
                    }
                ]
            }
        return {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {"id": name, "function": {"name": name, "arguments": json.dumps(args)}}
                        ]
                    }
                }
            ]
        }


async def prepare(durable, policy, image, plan=None):
    data_image = os.getenv("CALIBURN_SANDBOX_TEST_IMAGE")
    if not data_image:
        pytest.skip("Actual data-runner image required")
    queue, pid, task = proposal(durable, image, plan)
    serving = asyncio.create_task(Supervisor(queue, DockerExecutor(data_image)).serve())
    try:
        await asyncio.wait_for(Worker(durable, ModelFixture(pid)).run_once(), 30)
    finally:
        serving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await serving
    assert durable.get(task["id"])["state"] == "WAITING_APPROVAL"
    return queue, pid, task, policy.views(task["id"])[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("interrupt_before_commit", [False, True])
async def test_actual_reviewed_baseline_candidate_and_worker_evidence(
    durable, authority, test_image, monkeypatch, interrupt_before_commit
):
    policy, reviewer, _ = authority
    queue, pid, task, view = await prepare(durable, policy, test_image)
    assert view["binding"]["execution_permitted"] is True
    reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    original_commit = durable.commit
    interrupted = False

    def interrupted_commit(*args):
        nonlocal interrupted
        if interrupt_before_commit and not interrupted and args[3].get("name") == "repo_test":
            interrupted = True
            raise LostLease()
        return original_commit(*args)

    monkeypatch.setattr(durable, "commit", interrupted_commit)
    serving = asyncio.create_task(Supervisor(queue, ReviewedTestExecutor(test_image)).serve())
    try:
        await asyncio.wait_for(Worker(durable, ModelFixture(pid)).run_once(), 50)
    finally:
        serving.cancel()
        with pytest.raises(asyncio.CancelledError):
            await serving
    if interrupt_before_commit:
        assert interrupted
        with durable.engine.begin() as c:
            c.execute(
                update(tasks).where(tasks.c.id == task["id"]).values(lease_until=durable.now(c) - 1)
            )
        # No supervisor now: recovery must reuse the committed container evidence.
        await asyncio.wait_for(Worker(durable, ModelFixture(pid)).run_once(), 5)
    final = durable.get(task["id"])
    assert final["state"] == "COMPLETED", final["error"]
    assert (final["model_calls"], final["tool_calls"]) == (4, 4 if interrupt_before_commit else 3)
    with durable.engine.connect() as c:
        output = c.execute(
            select(jobs.c.result).where(
                jobs.c.task_id == task["id"], jobs.c.operation["tool"].as_string() == "repo_test"
            )
        ).scalar_one()
    assert output["data"]["source_executed"] is True
    assert policy.views(task["id"])[0]["source_executed"] is True
    assert output["data"]["baseline"]["exit_code"] == 1
    assert output["data"]["candidate"]["exit_code"] == 0
    assert "FAILED" in output["data"]["baseline"]["output"]
    assert "OK" in output["data"]["candidate"]["output"]
    for isolation in output["isolation"].values():
        assert isolation["uid"] == 10001 and isolation["root_readonly"]
        assert isolation["interfaces"] == ["lo"] and not isolation["docker_socket"]
        assert isolation["NoNewPrivs"] == "1" and isolation["Seccomp"] == "2"
    if (path := os.getenv("CALIBURN_EXECUTION_EVIDENCE")) and not interrupt_before_commit:
        Path(path).write_text(
            json.dumps(
                {
                    "fixtures": [
                        "model inference",
                        "reviewer identity",
                        "source and independent test plan",
                    ],
                    "actual": [
                        "PostgreSQL",
                        "worker",
                        "independent role approval",
                        "fresh Docker container per variant",
                    ],
                    "task_state": final["state"],
                    "model_calls": final["model_calls"],
                    "tool_calls": final["tool_calls"],
                    "binding": view["binding"],
                    "result": output,
                },
                indent=2,
            ),
            encoding="utf-8",
        )


def test_readonly_or_review_only_is_not_execution_authority(durable, authority):
    _policy, reviewer, _ = authority
    task, _, view = waiting(durable)
    reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    lease = durable.claim("not-execution-granted")
    step = durable.prepare(task["id"], lease["lease_token"], "TOOL", {})
    with pytest.raises(WorkspaceDenied):
        WorkspaceQueue(durable).request(
            task["id"],
            lease["lease_token"],
            step["id"],
            Operation(tool="repo_test", arguments={"request_ref": view["id"]}),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "revoke", "stale", "expired"])
async def test_execution_dispatch_lease_and_result_deny(durable, authority, test_image, action):
    policy, reviewer, _ = authority
    queue, _, task, view = await prepare(durable, policy, test_image)
    reviewer.decide(view["id"], view["binding_sha256"], "APPROVE", ttl_seconds=60)
    lease = durable.claim("execution-fixture", 120)
    step = durable.prepare(task["id"], lease["lease_token"], "TOOL", {})
    operation = Operation(tool="repo_test", arguments={"request_ref": view["id"]})
    queue.request(task["id"], lease["lease_token"], step["id"], operation)
    # Data supervisor never claims executable jobs; wrong immutable image also denies.
    assert queue.claim(test_image) is None
    assert queue.claim("sha256:" + "0" * 64, tools=("repo_test",)) is None
    job = queue.claim(test_image, lease_seconds=120, tools=("repo_test",))
    assert job
    if action == "cancel":
        durable.control(task["id"], "cancel")
    elif action == "revoke":
        reviewer.revoke(view["id"])
    elif action == "stale":
        with durable.engine.begin() as c:
            c.execute(
                update(jobs)
                .where(jobs.c.id == job["id"])
                .values(controller_until=durable.now(c) - 1)
            )
    else:
        original = durable.now
        durable.now = lambda c: original(c) + 61
    assert not queue.heartbeat(job)
    with pytest.raises((LostLease, WorkspaceDenied)):
        queue.finish(job, Result(ok=False, error="stale-fixture"))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source,expected",
    [
        ("while True: pass", "TIMEOUT"),
        ("print('x'*200000)", "OUTPUT_LIMIT"),
        ("raise RuntimeError('fixture crash')", "FAILED"),
    ],
)
async def test_actual_test_process_failures(test_image, source, expected):
    files = Bundle(files={"calc.py": source})
    plan = Bundle(files=PLAN)
    job = {
        "base_files": files.files,
        "candidate_files": files.files,
        "plan_files": plan.files,
        "request_ref": "r" * 36,
        "binding_sha256": "b" * 64,
        "binding": {
            "base_sha256": files.digest(),
            "candidate_sha256": files.digest(),
            "plan_sha256": plan.digest(),
        },
    }

    # Explicit synthetic admission for fixed driver qualification fixtures only.
    async def fixture_admission(_job):
        return True

    result = await ReviewedTestExecutor(test_image, guard=fixture_admission).execute(job)
    assert result.ok, result.error
    assert result.data["baseline"]["status"] == expected
    assert result.data["candidate"]["status"] == expected


@pytest.mark.asyncio
async def test_test_executor_has_no_implicit_admission(test_image):
    result = await ReviewedTestExecutor(test_image).execute({})
    assert not result.ok and result.error == "test_authorization_denied"


@pytest.mark.asyncio
async def test_actual_execution_network_root_and_credentials_denied(test_image):
    source = Bundle(files={"calc.py": "def total(a,b): return a+b\n"})
    plan = Bundle(
        files={
            "test_boundary.py": """import os, socket, unittest
from pathlib import Path
class Boundary(unittest.TestCase):
    def test_boundary(self):
        self.assertIsNone(os.getenv('CALIBURN_DATABASE_URL'))
        self.assertIsNone(os.getenv('CALIBURN_API_TOKEN'))
        self.assertFalse(Path('/var/run/docker.sock').exists())
        with self.assertRaises(OSError):
            Path('/etc/caliburn-test-write').write_text('denied')
        with socket.socket() as client:
            client.settimeout(0.2)
            with self.assertRaises(OSError):
                client.connect(('1.1.1.1', 443))
"""
        }
    )

    async def fixture_admission(_job):
        return True

    job = {
        "base_files": source.files,
        "candidate_files": source.files,
        "plan_files": plan.files,
        "request_ref": "r" * 36,
        "binding_sha256": "b" * 64,
        "binding": {
            "base_sha256": source.digest(),
            "candidate_sha256": source.digest(),
            "plan_sha256": plan.digest(),
        },
    }
    result = await ReviewedTestExecutor(test_image, guard=fixture_admission).execute(job)
    assert result.ok, result.error
    assert result.data["baseline"]["status"] == "PASSED"
    assert result.data["candidate"]["status"] == "PASSED"


@pytest.mark.asyncio
async def test_withdrawn_guard_prevents_second_container(test_image):
    source, plan = Bundle(files={"calc.py": SOURCE}), Bundle(files=PLAN)
    calls = 0

    async def fixture_admission(_job):
        nonlocal calls
        calls += 1
        return calls < 3

    job = {
        "base_files": source.files,
        "candidate_files": source.files,
        "plan_files": plan.files,
        "request_ref": "r" * 36,
        "binding_sha256": "b" * 64,
        "binding": {
            "base_sha256": source.digest(),
            "candidate_sha256": source.digest(),
            "plan_sha256": plan.digest(),
        },
    }
    result = await ReviewedTestExecutor(test_image, guard=fixture_admission).execute(job)
    assert not result.ok and result.error == "test_authorization_denied"
    assert calls == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["cancel", "revoke", "pause"])
async def test_active_reviewed_container_is_removed_on_revocation(
    durable, authority, test_image, action
):
    policy, reviewer, _ = authority
    queue, _, task, view = await prepare(
        durable, policy, test_image, {"test_wait.py": "import time\nwhile True: time.sleep(0.1)\n"}
    )
    reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    lease = durable.claim("active-test-fixture", 30)
    step = durable.prepare(task["id"], lease["lease_token"], "TOOL", {})
    queue.request(
        task["id"],
        lease["lease_token"],
        step["id"],
        Operation(tool="repo_test", arguments={"request_ref": view["id"]}),
    )
    started = asyncio.Event()
    names = []

    class ObservedExecutor(ReviewedTestExecutor):
        def command(self, name, **kwargs):
            names.append(name)
            return super().command(name, **kwargs)

        def payload(self, job):
            started.set()
            return super().payload(job)

    supervisor = Supervisor(queue, ObservedExecutor(test_image))
    running = asyncio.create_task(supervisor.run_once())
    await asyncio.wait_for(started.wait(), 10)
    await asyncio.sleep(0.3)
    if action == "revoke":
        reviewer.revoke(view["id"])
    else:
        durable.control(task["id"], action)
    await asyncio.wait_for(running, 10)
    assert len(names) == 1  # No candidate container starts after admission is withdrawn.
    for name in names:
        check = await asyncio.create_subprocess_exec(
            "docker",
            "inspect",
            name,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        assert await check.wait() != 0
    assert policy.views(task["id"])[0]["source_executed"] is None
