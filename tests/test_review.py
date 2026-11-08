"""Actual PostgreSQL role/ledger tests; identities and inference are synthetic fixtures."""

import asyncio
import hashlib
import json
import os
import subprocess
import sys
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError

from caliburn.app import app
from caliburn.policy.contracts import ReviewArgs
from caliburn.policy.review import ReviewDenied, ReviewPolicy
from caliburn.policy.schema import candidates, decisions, requests, reviewers
from caliburn.runtime.contracts import Submit
from caliburn.runtime.schema import tasks
from caliburn.runtime.store import Conflict
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle, Operation, Result
from caliburn.sandbox.control import DockerExecutor, Supervisor
from caliburn.sandbox.queue import WorkspaceQueue
from caliburn.sandbox.runner import run

SOURCE = "def total(a, b):\n    return a - b\n"
PATCH = {
    "path": "calc.py",
    "expected_sha256": hashlib.sha256(SOURCE.encode()).hexdigest(),
    "old": "a - b",
    "new": "a + b",
}


def setup(durable):
    queue = WorkspaceQueue(durable)
    wid = queue.register(Bundle(files={"calc.py": SOURCE}), propose_patch=True, request_review=True)
    policy = ReviewPolicy(durable)
    pid = policy.register_plan(
        wid, {"test_calc.py": "assert total(2, 3) == 5\n"}, "sha256:" + "a" * 64
    )
    task = durable.submit(
        Submit(prompt="prepare candidate and request independent review", workspace_ref=wid)
    )
    return queue, pid, task


def waiting(durable):
    queue, pid, task = setup(durable)
    lease = durable.claim("fixture", 30)
    token = lease["lease_token"]
    step = durable.prepare(task["id"], token, "TOOL", {})
    op = Operation(tool="repo_patch", arguments=PATCH)
    queue.request(task["id"], token, step["id"], op)
    job = queue.claim("sha256:" + "a" * 64)
    # Fixed data runner only; no candidate/test file imports or execution.
    result = Result.model_validate(
        run({"files": job["files"], "digest": job["digest"], "operation": job["operation"]})
    )
    queue.finish(job, result)
    result = queue.poll(task["id"], token, job["id"])
    policy = ReviewPolicy(durable)
    args = ReviewArgs(candidate_ref=result.candidate_ref, plan_ref=pid)
    assert policy.ensure(task["id"], token, args, "c" * 64) is None
    return task, args, policy.views(task["id"])[0]


def test_review_authority_fails_closed_without_postgres(durable):
    if durable.engine.dialect.name != "sqlite":
        pytest.skip("SQLite denial only")
    with pytest.raises(ReviewDenied):
        ReviewPolicy(durable).configure_reviewer("fixture", "fixture")


def test_temp_mapping_cannot_restore_repository_reviewer(durable, authority):
    _, reviewer, name = authority
    _, _, view = waiting(durable)
    with durable.engine.begin() as c:
        c.execute(update(reviewers).where(reviewers.c.db_role == name).values(enabled="no"))
    with reviewer.store.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(
            text(
                f'CREATE TEMP TABLE policy_reviewers AS SELECT * FROM "{schema}".policy_reviewers WHERE false'
            )
        )
        c.execute(
            text(
                "INSERT INTO pg_temp.policy_reviewers (db_role,principal,tenant,enabled) VALUES (current_user,'forged-independent-reviewer','development','yes')"
            )
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            c.execute(
                insert(decisions).values(
                    id=str(uuid4()),
                    request_id=view["id"],
                    reviewer_role=name,
                    decision="APPROVE",
                    binding_digest=view["binding_sha256"],
                    created_at=durable.now(c),
                    expires_at=view["expires_at"],
                )
            )


def test_exact_binding_independence_and_immutable_evidence(durable, authority):
    policy, reviewer, name = authority
    task, args, view = waiting(durable)
    assert view["status"] == "PENDING" and view["source_executed"] is False
    assert view["binding"]["scope"] == "sandbox_test_only"
    with TestClient(app) as client:
        url = f"/api/v1/tasks/{task['id']}/reviews"
        assert client.get(url).status_code == 401
        auth = {"Authorization": "Bearer test-service-token-secret"}
        assert client.get(url, headers=auth).json()[0]["binding_sha256"] == view["binding_sha256"]
        assert client.post(f"/api/v1/tasks/{task['id']}/resume", headers=auth).status_code == 409
        assert client.post(f"/api/v1/tasks/{task['id']}/approve", headers=auth).status_code == 404
    inspected = reviewer.inspect(view["id"])
    assert "a + b" in inspected["candidate_files"]["calc.py"]
    assert inspected["binding_sha256"] == view["binding_sha256"]
    with pytest.raises(ReviewDenied):
        policy.inspect(view["id"])
    with pytest.raises(Conflict):
        durable.control(task["id"], "resume")
    with pytest.raises(ReviewDenied):
        policy.decide(view["id"], view["binding_sha256"], "APPROVE")
    with pytest.raises(ReviewDenied):
        reviewer.decide(view["id"], "0" * 64, "APPROVE")
    with pytest.raises(DBAPIError), reviewer.store.engine.begin() as c:
        c.execute(insert(candidates).values(id=str(uuid4())))
    with pytest.raises(DBAPIError), durable.engine.begin() as c:
        c.execute(update(candidates).values(artifact_digest="0" * 64))
    # Forging the JSON/SQL reviewer name cannot replace current_user authority.
    with pytest.raises(DBAPIError), durable.engine.begin() as c:
        now = durable.now(c)
        c.execute(
            insert(decisions).values(
                id=str(uuid4()),
                request_id=view["id"],
                decision="APPROVE",
                reviewer_role=name,
                binding_digest=view["binding_sha256"],
                created_at=now,
                expires_at=now + 60,
            )
        )
    reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    assert durable.get(task["id"])["state"] == "QUEUED"
    with pytest.raises(ReviewDenied):
        reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    lease = durable.claim("resumed", 30)
    output = policy.ensure(task["id"], lease["lease_token"], args, "c" * 64)
    assert output["data"]["review_status"] == "APPROVED_FOR_SANDBOX_TEST"
    assert output["data"]["source_executed"] is False
    reviewer.revoke(view["id"])
    assert durable.get(task["id"])["error"] == "review_revoked"
    assert policy.views(task["id"])[0]["status"] == "REVOKED"


@pytest.mark.parametrize("action", ["REJECT", "cancel", "timeout", "expired"])
def test_review_failure_paths(durable, authority, action):
    policy, reviewer, _ = authority
    task, _, view = waiting(durable)
    if action == "REJECT":
        reviewer.decide(view["id"], view["binding_sha256"], "REJECT")
        assert durable.get(task["id"])["error"] == "review_rejected"
    elif action == "cancel":
        durable.control(task["id"], "cancel")
        with pytest.raises(ReviewDenied):
            reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    elif action == "timeout":
        with durable.engine.begin() as c:
            c.execute(
                update(tasks).where(tasks.c.id == task["id"]).values(deadline=durable.now(c) - 1)
            )
        assert durable.claim("sweeper") is None
        assert durable.get(task["id"])["state"] == "TIMED_OUT"
    else:
        reviewer.decide(view["id"], view["binding_sha256"], "APPROVE", ttl_seconds=1)
        # Advance the owning clock without a wall-clock sleep.
        original = durable.now
        durable.now = lambda c: original(c) + 2
        assert policy.views(task["id"])[0]["status"] == "EXPIRED"
        lease = durable.claim("expired-consumer")
        with pytest.raises(ReviewDenied):
            policy.ensure(
                task["id"],
                lease["lease_token"],
                ReviewArgs(
                    candidate_ref=view["binding"]["candidate_ref"],
                    plan_ref=view["binding"]["plan_ref"],
                ),
                "c" * 64,
            )


def test_model_cannot_supply_approval_authority():
    with pytest.raises(ValidationError):
        ReviewArgs(candidate_ref="c" * 36, plan_ref="p" * 36, approved=True)


def test_cross_task_candidate_and_revoked_workspace_denied(durable, authority):
    policy, reviewer, _ = authority
    task, args, view = waiting(durable)
    other = durable.submit(
        Submit(
            prompt="reuse someone else's candidate", workspace_ref=view["binding"]["workspace_ref"]
        )
    )
    lease = durable.claim("different-task")
    assert lease["id"] == other["id"]
    with pytest.raises(ReviewDenied):
        policy.ensure(other["id"], lease["lease_token"], args, "c" * 64)
    WorkspaceQueue(durable).revoke(view["binding"]["workspace_ref"])
    with pytest.raises(ReviewDenied):
        reviewer.decide(view["id"], view["binding_sha256"], "APPROVE")
    assert policy.views(task["id"])[0]["status"] == "INVALIDATED"


@pytest.mark.asyncio
async def test_worker_real_docker_review_restart_and_resume(durable, authority):
    image = os.getenv("CALIBURN_SANDBOX_TEST_IMAGE")
    if not image:
        pytest.skip("Set CALIBURN_SANDBOX_TEST_IMAGE for actual Docker validation")
    policy, reviewer, _ = authority
    queue, pid, task = setup(durable)

    class ModelFixture:
        async def complete(self, messages, tools):
            observed = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if not observed:
                name, args = "repo_patch", PATCH
            elif len(observed) == 1:
                name, args = (
                    "repo_request_review",
                    {"candidate_ref": observed[0]["candidate_ref"], "plan_ref": pid},
                )
            else:
                assert observed[-1]["data"]["source_executed"] is False
                return {
                    "choices": [
                        {"message": {"content": "Reviewed candidate; execution remains disabled."}}
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "id": name,
                                    "function": {"name": name, "arguments": json.dumps(args)},
                                }
                            ]
                        }
                    }
                ]
            }

    supervisor = asyncio.create_task(Supervisor(queue, DockerExecutor(image)).serve())
    try:
        await asyncio.wait_for(Worker(durable, ModelFixture()).run_once(), 30)
    finally:
        supervisor.cancel()
        with pytest.raises(asyncio.CancelledError):
            await supervisor
    checkpoint = durable.get(task["id"])
    assert checkpoint["state"] == "WAITING_APPROVAL", checkpoint["error"]
    assert (checkpoint["model_calls"], checkpoint["tool_calls"]) == (2, 1)
    view = policy.views(task["id"])[0]
    env = dict(
        os.environ,
        CALIBURN_DATABASE_URL=reviewer.store.engine.url.render_as_string(hide_password=False),
    )
    for arguments in (
        ["inspect", "--request", view["id"]],
        [
            "decide",
            "--request",
            view["id"],
            "--binding-sha256",
            view["binding_sha256"],
            "--decision",
            "APPROVE",
        ],
    ):
        result = await asyncio.to_thread(
            subprocess.run,
            [sys.executable, "-m", "caliburn.policy.cli", *arguments],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        assert result.returncode == 0, "Reviewer CLI failed (output withheld)"
        assert json.loads(result.stdout)
    # New worker, no supervisor: the committed patch must not run again.
    await Worker(durable, ModelFixture()).run_once()
    final = durable.get(task["id"])
    assert final["state"] == "COMPLETED", final["error"]
    assert (final["model_calls"], final["tool_calls"]) == (3, 2)
    with durable.engine.connect() as c:
        assert len(c.execute(select(requests)).all()) == 1
        assert len(c.execute(select(candidates)).all()) == 1
