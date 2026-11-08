"""Factory review+actual isolated tests. Models/identities synthetic, DB/Docker real."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_factory import AUTH, call, count, proposal
from test_factory_checks import candidate, pending, until

from caliburn.app import app
from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.schema import tasks
from caliburn.runtime.store import Conflict
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle
from caliburn.sandbox.control import Supervisor
from caliburn.tool_factory.execution_contracts import EXEC_DIGEST, ExecutionReviewArgs
from caliburn.tool_factory.execution_control import FactoryTestExecutor
from caliburn.tool_factory.execution_queue import ExecutionQueue
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.schema import (
    check_jobs,
    check_reports,
    exec_decisions,
    exec_jobs,
    exec_requests,
)
from caliburn.tool_factory.service import FactoryDenied
from caliburn.tool_factory.verifier import StaticVerifier

IMAGE = os.getenv("CALIBURN_REVIEWED_TEST_IMAGE")


async def plan(store, verifier_store, *, value=None, image=None, oracle_cases=None):
    cid = candidate(store, value)
    tid, _, _, _ = pending(store, cid)
    assert await StaticVerifier(verifier_store).run_once()
    with store.engine.connect() as c:
        report = c.scalar(
            select(check_reports.c.id)
            .join(check_jobs, check_jobs.c.id == check_reports.c.job_id)
            .where(check_jobs.c.task_id == tid)
        )
    store.control(tid, "cancel")
    independent = Bundle(
        files={
            "test_independent.py": "import unittest\nfrom double import run\nclass Independent(unittest.TestCase):\n    def test_extra_case(self):\n        self.assertEqual(run(value=5), {'value':10})\n"
        }
    )
    return Qualification(store).register_plan(
        cid, report, independent, image or IMAGE or "sha256:" + "0" * 64, oracle_cases=oracle_cases
    )


class ExecutionModel:
    def __init__(self, pid):
        self.pid = pid

    async def complete(self, messages, tools):
        last = messages[-1]
        if last["role"] != "tool":
            message = {
                "content": None,
                "tool_calls": [call("capability_request_execution", {"plan_ref": self.pid})],
            }
        elif last["name"] == "capability_request_execution":
            admission = json.loads(last["content"])
            message = {
                "content": None,
                "tool_calls": [
                    call("capability_execute_tests", {"request_ref": admission["request_ref"]})
                ],
            }
        else:
            observed = json.loads(last["content"])
            message = {
                "content": json.dumps(
                    {
                        "status": (observed.get("data") or {}).get("run", {}).get("status"),
                        "ok": observed["ok"],
                    }
                )
            }
        return {"choices": [{"message": message}]}


async def waiting(store, pid):
    task = store.submit(
        Submit(prompt="Qualify inert factory artifact"), allow_factory_execution=True
    )
    assert await Worker(store, ExecutionModel(pid), output_tokens=4096).run_once()
    assert store.get(task["id"])["state"] == "WAITING_APPROVAL"
    with store.engine.connect() as c:
        req = (
            c.execute(select(exec_requests).where(exec_requests.c.task_id == task["id"]))
            .mappings()
            .one()
        )
    return task["id"], dict(req)


async def approved_worker(store, reviewer, pid):
    tid, req = await waiting(store, pid)
    reviewer.decide(req["id"], req["sha256"], "APPROVE")
    running = asyncio.create_task(Worker(store, ExecutionModel(pid), output_tokens=4096).run_once())
    await until(lambda: count(store, exec_jobs) == 1)
    return tid, req, running


@pytest.mark.parametrize("bad", [False, True])
async def test_real_docker_factory_qualification(
    durable, factory_verifier, factory_execution_authority, bad
):
    if not IMAGE:
        pytest.skip("Set CALIBURN_REVIEWED_TEST_IMAGE for real Factory Docker tests")
    owner, reviewer, executor_store, _ = factory_execution_authority
    value = proposal().model_copy(deep=True)
    if bad:
        value.bundle.sources["double.py"] = "def run(value): return {'value': value*3}\n"
    pid = await plan(durable, factory_verifier[2], value=value)
    tid, req = await waiting(durable, pid)
    assert count(durable, exec_jobs) == 0
    inspected = reviewer.inspect(req["id"])
    assert inspected["status"] == "PENDING" and not inspected["dispatch_attempted"]
    with pytest.raises(FactoryDenied):
        owner.decide(req["id"], req["sha256"], "APPROVE")
    with pytest.raises(Conflict):
        durable.control(tid, "resume")
    with pytest.raises(FactoryDenied):
        reviewer.decide(req["id"], "0" * 64, "APPROVE")
    reviewer.decide(req["id"], req["sha256"], "APPROVE")
    assert durable.get(tid)["state"] == "WAITING_APPROVAL"  # reviewer has no Task writes
    worker = asyncio.create_task(
        Worker(durable, ExecutionModel(pid), output_tokens=4096).run_once()
    )
    try:
        await until(lambda: count(durable, exec_jobs) == 1)
        assert ExecutionQueue(executor_store).claim("sha256:" + "f" * 64) is None
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "caliburn.tool_factory.execution_control",
            "--image",
            IMAGE,
            "--once",
            env=dict(
                os.environ,
                CALIBURN_DATABASE_URL=executor_store.engine.url.render_as_string(
                    hide_password=False
                ),
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, error = await asyncio.wait_for(process.communicate(), 45)
        assert process.returncode == 0, error.decode()
        await asyncio.wait_for(worker, 10)
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    assert durable.get(tid)["state"] == "COMPLETED"
    with durable.engine.connect() as c:
        job = c.execute(select(exec_jobs)).mappings().one()
    proof = job["result"]["data"]
    assert proof["source_executed"] and not proof["production_approved"]
    assert proof["run"]["status"] == ("FAILED" if bad else "PASSED")
    assert (
        proof["binding_sha256"] == req["sha256"] and proof["executor_role"] != req["creator_role"]
    )
    assert "test_declared_fixtures" in proof["run"]["output"]
    if os.getenv("CALIBURN_RECORD_FACTORY_EVIDENCE") == "true":
        path = (
            Path(__file__).resolve().parents[1]
            / "docs"
            / "evidence"
            / ("m3-execution-failed.json" if bad else "m3-execution-passed.json")
        )
        path.write_text(
            json.dumps(
                {
                    "fixture_identities": True,
                    "fixture_model": True,
                    "task_id": tid,
                    "request_ref": req["id"],
                    "binding": req["binding"],
                    "result": job["result"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
    with TestClient(app) as client:
        route = f"/api/v1/tasks/{tid}/factory-execution-reviews"
        assert client.get(route).status_code == 401
        assert client.get(route, headers=AUTH).json()[0]["dispatch_attempted"]
        assert client.post(f"/api/v1/tasks/{tid}/approve", headers=AUTH).status_code == 404


@pytest.mark.parametrize("action", ["REJECT", "revoke", "reviewer_disabled", "expired", "cancel"])
async def test_admission_denials_before_dispatch(
    durable, factory_verifier, factory_execution_authority, action
):
    owner, reviewer, executor_store, names = factory_execution_authority
    pid = await plan(durable, factory_verifier[2])
    tid, req = await waiting(durable, pid)
    reviewer.decide(req["id"], req["sha256"], "REJECT" if action == "REJECT" else "APPROVE")
    if action == "revoke":
        reviewer.revoke(req["id"])
    elif action == "reviewer_disabled":
        owner.disable(names[0])
    elif action == "expired":
        with durable.engine.begin() as c:
            c.execute(update(tasks).where(tasks.c.id == tid).values(deadline=durable.now(c) - 1))
    elif action == "cancel":
        durable.control(tid, "cancel")
    await Worker(durable, ExecutionModel(pid), output_tokens=4096).run_once()
    assert durable.get(tid)["state"] in {"FAILED", "CANCELLED", "TIMED_OUT"}
    assert count(durable, exec_jobs) == 0
    assert ExecutionQueue(executor_store).claim(IMAGE or "sha256:" + "0" * 64) is None


@pytest.mark.parametrize("action", ["revoke", "cancel", "pause"])
async def test_live_container_stop_cleanup(
    durable, factory_verifier, factory_execution_authority, action
):
    if not IMAGE:
        pytest.skip("Set CALIBURN_REVIEWED_TEST_IMAGE for actual Factory cancellation")
    _, reviewer, executor_store, _ = factory_execution_authority
    value = proposal().model_copy(deep=True)
    value.bundle.sources["double.py"] = "def run(value):\n    while True: pass\n"
    pid = await plan(durable, factory_verifier[2], value=value)
    tid, req, worker = await approved_worker(durable, reviewer, pid)
    ready = asyncio.Event()

    class NotifyingExecutor(FactoryTestExecutor):
        def payload(self, job):
            ready.set()
            return super().payload(job)

    executor = NotifyingExecutor(IMAGE)
    supervisor = asyncio.create_task(
        Supervisor(ExecutionQueue(executor_store), executor).run_once()
    )
    try:
        await asyncio.wait_for(ready.wait(), 20)
        if action == "revoke":
            reviewer.revoke(req["id"])
        else:
            durable.control(tid, action)
        await asyncio.wait_for(supervisor, 15)
        await asyncio.wait_for(worker, 10)
    finally:
        for pending_task in (worker, supervisor):
            if not pending_task.done():
                pending_task.cancel()
        await asyncio.gather(worker, supervisor, return_exceptions=True)
    with durable.engine.connect() as c:
        row = c.execute(select(exec_jobs)).mappings().one()
    assert row["result"] is None
    assert durable.get(tid)["state"] in {"FAILED", "CANCELLED", "PAUSED"}


async def test_runtime_cannot_forge_or_bypass_factory_authority(
    durable, factory_verifier, factory_execution_authority
):
    _, reviewer, _executor_store, _ = factory_execution_authority
    pid = await plan(durable, factory_verifier[2])
    tid, req = await waiting(durable, pid)
    with pytest.raises(DBAPIError), durable.engine.begin() as c:
        c.execute(
            insert(exec_decisions).values(
                id=req["id"],
                request_id=req["id"],
                reviewer_role="forged",
                decision="APPROVE",
                binding_sha256=req["sha256"],
                created_at=durable.now(c),
                expires_at=req["expires_at"],
            )
        )
    with pytest.raises(FactoryDenied):
        ExecutionQueue(durable).claim(IMAGE or "sha256:" + "0" * 64)
    assert count(durable, exec_decisions) == 0
    assert durable.get(tid)["state"] == "WAITING_APPROVAL"
    assert durable.get(tid)["policy"]["exec_digest"] == EXEC_DIGEST
    with pytest.raises(DBAPIError), reviewer.store.engine.begin() as c:
        c.execute(update(tasks).values(state="QUEUED"))


async def test_actual_process_crash_reuses_persisted_execution(
    durable, factory_verifier, factory_execution_authority
):
    if not IMAGE:
        pytest.skip("Set CALIBURN_REVIEWED_TEST_IMAGE for actual recovery")
    _, reviewer, executor_store, _ = factory_execution_authority
    pid = await plan(durable, factory_verifier[2])
    tid, req = await waiting(durable, pid)
    reviewer.decide(req["id"], req["sha256"], "APPROVE")
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        str(Path(__file__).with_name("factory_execution_crash_fixture.py")),
        env=dict(
            os.environ,
            CALIBURN_DATABASE_URL=durable.engine.url.render_as_string(hide_password=False),
            CALIBURN_FACTORY_TEST_PLAN=pid,
        ),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        await until(lambda: count(durable, exec_jobs) == 1)
        assert await Supervisor(
            ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)
        ).run_once()
        await asyncio.wait_for(process.wait(), 20)
        assert process.returncode == 73
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    await asyncio.sleep(1.2)  # natural expiry of dead worker's1-second lease
    await Worker(durable, ExecutionModel(pid), output_tokens=4096).run_once()
    result = durable.get(tid)
    assert result["state"] == "COMPLETED" and result["tool_calls"] == 3
    with durable.engine.connect() as c:
        job = c.execute(select(exec_jobs)).mappings().one()
    assert job["attempts"] == 1 and job["result"]["data"]["run"]["status"] == "PASSED"
    assert ExecutionQueue(executor_store).claim(IMAGE) is None
    assert len([e for e in durable.replay(tid) if e["type"] == "FACTORY_TEST_QUEUED"]) == 1


@pytest.mark.parametrize("kind", ["timeout", "output"])
async def test_actual_factory_resource_failures(
    durable, factory_verifier, factory_execution_authority, kind
):
    if not IMAGE:
        pytest.skip("Set CALIBURN_REVIEWED_TEST_IMAGE for actual resource tests")
    _, reviewer, executor_store, _ = factory_execution_authority
    value = proposal().model_copy(deep=True)
    value.bundle.sources["double.py"] = (
        "def run(value):\n    while True: pass\n"
        if kind == "timeout"
        else "def run(value):\n    print('x'*20000)\n    return {'value':value*2}\n"
    )
    pid = await plan(durable, factory_verifier[2], value=value)
    tid, _, worker = await approved_worker(durable, reviewer, pid)
    try:
        assert await Supervisor(
            ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)
        ).run_once()
        await asyncio.wait_for(worker, 10)
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    assert durable.get(tid)["state"] == "COMPLETED"
    with durable.engine.connect() as c:
        proof = c.scalar(select(exec_jobs.c.result))["data"]
    assert proof["run"]["status"] == ("TIMEOUT" if kind == "timeout" else "OUTPUT_LIMIT")
    assert len(proof["run"]["output"]) <= 16384 and not proof["production_approved"]


async def test_unrelated_waits_do_not_starve_approved_factory_task(
    durable, factory_verifier, factory_execution_authority
):
    _, reviewer, _, _ = factory_execution_authority
    pid = await plan(durable, factory_verifier[2])
    for _ in range(21):
        task = durable.submit(Submit(prompt="Unrelated independent wait"))
        claimed = durable.claim("unrelated", 30)
        with durable.engine.begin() as c:
            row = durable._owned(c, task["id"], claimed["lease_token"])
            durable._end(c, row, "WAITING_APPROVAL")
    tid, req = await waiting(durable, pid)
    reviewer.decide(req["id"], req["sha256"], "APPROVE")
    assert durable.claim("awake", 30)["id"] == tid


async def test_flag_and_static_block_deny_execution_request(
    durable, factory_verifier, factory_execution_authority
):
    pid = await plan(durable, factory_verifier[2])
    task = durable.submit(Submit(prompt="No execution grant"), allow_capability_proposals=True)
    await Worker(durable, ExecutionModel(pid), output_tokens=4096).run_once()
    assert durable.get(task["id"])["error"] == "tool_policy_denied"
    value = proposal().model_copy(deep=True)
    value.bundle.manifest.version = "2.0.0"
    value.bundle.sources["double.py"] = "import os\ndef run(value): return {'value':value*2}\n"
    cid = candidate(durable, value)
    tid, _, _, _ = pending(durable, cid)
    assert await StaticVerifier(factory_verifier[2]).run_once()
    with durable.engine.connect() as c:
        rid = c.scalar(select(check_reports.c.id).order_by(check_reports.c.created_at.desc()))
    durable.control(tid, "cancel")
    with pytest.raises(FactoryDenied):
        Qualification(durable).register_plan(
            cid, rid, Bundle(files={"test_x.py": "pass"}), IMAGE or "sha256:" + "0" * 64
        )
    assert count(durable, exec_requests) == 0


@pytest.mark.parametrize("scope", ["actor", "tenant"])
async def test_plan_scope_cannot_be_borrowed(
    durable, factory_verifier, factory_execution_authority, scope
):
    pid = await plan(durable, factory_verifier[2])
    task = durable.submit(
        Submit(prompt="borrow plan denied"), allow_factory_execution=True, **{scope: "other"}
    )
    await Worker(durable, ExecutionModel(pid), output_tokens=4096).run_once()
    observed = durable.get(task["id"], actor=task["actor"], tenant=task["tenant"])
    assert observed["state"] == "FAILED" and count(durable, exec_requests) == 0


async def test_review_receipt_cannot_substitute_another_plan(
    durable, factory_verifier, factory_execution_authority
):
    _, reviewer, _, _ = factory_execution_authority
    one = await plan(durable, factory_verifier[2])
    two = await plan(durable, factory_verifier[2])
    tid, req = await waiting(durable, one)
    reviewer.decide(req["id"], req["sha256"], "APPROVE")
    claimed = durable.claim("receipt", 30)
    with pytest.raises(FactoryDenied):
        Qualification(durable).ensure(
            tid, claimed["lease_token"], ExecutionReviewArgs(plan_ref=two), req["call_key"]
        )
    proof = Qualification(durable).ensure(
        tid, claimed["lease_token"], ExecutionReviewArgs(plan_ref=one), req["call_key"]
    )
    assert proof["request_ref"] == req["id"] and not proof["source_executed"]


async def test_server_only_execution_flag(
    durable, factory_verifier, factory_execution_authority, monkeypatch
):
    pid = await plan(durable, factory_verifier[2])
    monkeypatch.setenv("CALIBURN_ALLOW_FACTORY_EXECUTION", "true")
    get_settings.cache_clear()
    with TestClient(app) as client:
        assert (
            client.post(
                "/api/v1/tasks",
                headers=AUTH,
                json={"prompt": "client cannot grant", "allow_factory_execution": True},
            ).status_code
            == 422
        )
        response = client.post("/api/v1/tasks", headers=AUTH, json={"prompt": "server admitted"})
    assert response.status_code == 202
    tid = response.json()["id"]
    assert "capability_execute_tests" in durable.get(tid)["policy"]["tools"]
    await Worker(durable, ExecutionModel(pid), output_tokens=4096).run_once()
    assert durable.get(tid)["state"] == "WAITING_APPROVAL" and count(durable, exec_jobs) == 0


async def test_temporary_table_cannot_restore_disabled_review_authority(
    durable, factory_verifier, factory_execution_authority
):
    owner, reviewer, _, names = factory_execution_authority
    pid = await plan(durable, factory_verifier[2])
    _, req = await waiting(durable, pid)
    owner.disable(names[0])
    with reviewer.store.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(
            text(
                f'CREATE TEMP TABLE factory_exec_roles AS SELECT * FROM "{schema}".factory_exec_roles WHERE false'
            )
        )
        c.execute(
            text(
                "INSERT INTO pg_temp.factory_exec_roles (db_role,principal,tenant,kind,enabled) VALUES (current_user,'forged-independent-reviewer','development','REVIEWER','yes')"
            )
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            c.execute(
                insert(exec_decisions).values(
                    id=req["id"],
                    request_id=req["id"],
                    reviewer_role=names[0],
                    decision="APPROVE",
                    binding_sha256=req["sha256"],
                    created_at=durable.now(c),
                    expires_at=req["expires_at"],
                )
            )
    assert count(durable, exec_decisions) == 0
