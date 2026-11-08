"""Host comparison cannot inherit the subject's forged unittest result."""

import asyncio
import json

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from test_factory import proposal
from test_factory_execution import IMAGE, approved_worker, plan

from caliburn.runtime.store import LostLease
from caliburn.sandbox.contracts import Result
from caliburn.sandbox.control import SandboxFailure, Supervisor
from caliburn.tool_factory.artifact_integrity import ArtifactDenied
from caliburn.tool_factory.execution_control import FactoryTestExecutor, OracleExecutor
from caliburn.tool_factory.execution_queue import ExecutionQueue
from caliburn.tool_factory.oracle import OracleProof, parse_json, same
from caliburn.tool_factory.schema import exec_jobs


@pytest.mark.parametrize(
    "raw",
    [
        b'{"value":1,"value":2}',
        b'{"value":NaN}',
        b'{"value":1e10000}',
        b"[" * 70 + b"0" + b"]" * 70,
        b"x" * 32769,
    ],
)
def test_untrusted_oracle_json_is_bounded(raw):
    with pytest.raises(ValueError):
        parse_json(raw)


def test_child_pass_bit_and_incomplete_checks_are_not_authority():
    executor = OracleExecutor(FactoryTestExecutor("sha256:" + "0" * 64))
    with pytest.raises(SandboxFailure):
        executor.validate({}, b'{"value":4,"passed":true}')
    with pytest.raises(ValidationError):
        OracleProof(plan_sha256="0" * 64, total=2, checked=1, status="PASSED")
    assert not same({"v": [True]}, {"v": [1]})
    assert not same({"v": 4, "extra": 1}, {"v": 4})


@pytest.mark.parametrize("attack", ["exit", "assertion", "success_flag"])
async def test_real_forged_child_pass_is_rejected(
    durable, factory_verifier, factory_execution_authority, artifact_signer, attack
):
    if not IMAGE:
        pytest.skip("Actual reviewed-test/oracle image required")
    _, reviewer, executor_store, _ = factory_execution_authority
    candidate = proposal().model_copy(deep=True)
    if attack == "exit":
        candidate.bundle.sources["double.py"] = "def run(value):\n    return {'value':value * 3}\n"
        candidate.bundle.tests["test_double.py"] = (
            "import unittest\ndef stop(self):\n    raise SystemExit(0)\nunittest.TestResult.wasSuccessful = stop\n"
        )
    else:
        candidate.bundle.sources["double.py"] = "def run(value):\n    return {'value':value * 3}\n"
        if attack == "assertion":
            candidate.bundle.sources["double.py"] = (
                "import unittest\nunittest.TestCase.assertEqual = lambda *args, **kwargs: None\n"
                + candidate.bundle.sources["double.py"]
            )
        else:
            candidate.bundle.tests["test_double.py"] = (
                "import unittest\nunittest.TestResult.wasSuccessful = lambda self: True\n"
            )
    pid = await plan(durable, factory_verifier[2], value=candidate)
    tid, _, worker = await approved_worker(durable, reviewer, pid)
    assert await Supervisor(ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)).run_once()
    await asyncio.wait_for(worker, 15)
    with durable.engine.connect() as c:
        job = c.execute(select(exec_jobs)).mappings().one()
    result = job["result"]
    assert not result["ok"] and result["error"] == "factory_oracle_failed"
    assert result["isolation"]["untrusted_test_run"]["exit_code"] == 0
    assert result["isolation"]["host_oracle"]["status"] == "FAILED"
    assert result["isolation"]["host_oracle"]["checked"] == 0
    _, signer, private, _, _, _ = artifact_signer
    with pytest.raises(ArtifactDenied):
        signer.publish(job["id"], private)
    assert (
        durable.get(tid)["state"] == "COMPLETED"
    )  # task observed rejection; not a passed candidate


async def test_real_independent_vectors_and_expected_values_stay_on_host(
    durable, factory_verifier, factory_execution_authority, monkeypatch
):
    if not IMAGE:
        pytest.skip("Actual reviewed-test/oracle image required")
    _, reviewer, executor_store, _ = factory_execution_authority
    cases = [
        {"name": "negative", "input": {"value": -17}, "expected": {"value": -34}},
        {"name": "independent", "input": {"value": 1345669}, "expected": {"value": 2691338}},
    ]
    pid = await plan(durable, factory_verifier[2], oracle_cases=cases)
    tid, _, worker = await approved_worker(durable, reviewer, pid)
    payloads = []
    original = OracleExecutor.payload

    def capture(self, job):
        raw = original(self, job)
        payloads.append(json.loads(raw))
        assert b"2691338" not in raw and b"expected" not in raw
        return raw

    monkeypatch.setattr(OracleExecutor, "payload", capture)
    test_payload = FactoryTestExecutor.payload

    def capture_tests(self, job):
        raw = test_payload(self, job)
        assert b"2691338" not in raw
        assert "caliburn_host_oracle.json" not in json.loads(raw)["plan"]
        return raw

    monkeypatch.setattr(FactoryTestExecutor, "payload", capture_tests)
    assert await Supervisor(ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)).run_once()
    await asyncio.wait_for(worker, 15)
    assert len(payloads) == 2
    assert all(set(p) == {"files", "source_sha256", "entrypoint", "input"} for p in payloads)
    with durable.engine.connect() as c:
        result = c.execute(select(exec_jobs.c.result)).scalar_one()
    assert result["data"]["run"]["status"] == "PASSED"
    proof = result["isolation"]["host_oracle"]
    assert proof["status"] == "PASSED" and proof["checked"] == proof["total"] == 2
    assert durable.get(tid)["state"] == "COMPLETED"


async def test_executor_cannot_publish_bare_pass_without_host_checks(
    durable, factory_verifier, factory_execution_authority
):
    _, reviewer, executor_store, _ = factory_execution_authority
    pid = await plan(durable, factory_verifier[2])
    _, _, worker = await approved_worker(durable, reviewer, pid)
    queue = ExecutionQueue(executor_store)
    job = queue.claim(IMAGE or "sha256:" + "0" * 64)
    fake = Result(
        ok=True,
        data={
            "status": "PASSED",
            "exit_code": 0,
            "output": "SYNTHETIC FORGED EXIT ONLY",
            "truncated": False,
            "source_sha256": job["binding"]["source_sha256"],
            "plan_sha256": job["binding"]["plan_sha256"],
        },
    )
    try:
        with pytest.raises((ValueError, LostLease)):
            queue.finish(job, fake)
        with durable.engine.connect() as c:
            assert c.execute(select(exec_jobs.c.result)).scalar_one() is None
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("action", ["revoke", "timeout"])
async def test_revoke_during_oracle_removes_live_container(
    durable, factory_verifier, factory_execution_authority, monkeypatch, action
):
    if not IMAGE:
        pytest.skip("Actual reviewed-test/oracle image required")
    _, reviewer, executor_store, _ = factory_execution_authority
    value = proposal().model_copy(deep=True)
    value.bundle.sources["double.py"] = (
        "def run(value):\n    if value == 7:\n        while True: pass\n    return {'value':value*2}\n"
    )
    cases = [{"name": "slow", "input": {"value": 7}, "expected": {"value": 14}}]
    pid = await plan(durable, factory_verifier[2], value=value, oracle_cases=cases)
    tid, req, worker = await approved_worker(durable, reviewer, pid)
    ready = asyncio.Event()
    original = OracleExecutor.payload

    def capture(self, job):
        ready.set()
        return original(self, job)

    monkeypatch.setattr(OracleExecutor, "payload", capture)
    supervisor = asyncio.create_task(
        Supervisor(ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)).run_once()
    )
    try:
        await asyncio.wait_for(ready.wait(), 20)
        if action == "revoke":
            reviewer.revoke(req["id"])
        await asyncio.wait_for(supervisor, 15)
        await asyncio.wait_for(worker, 15)
        with durable.engine.connect() as c:
            result = c.execute(select(exec_jobs.c.result)).scalar_one()
        if action == "revoke":
            assert result is None and durable.get(tid)["state"] == "FAILED"
        else:
            assert not result["ok"] and result["error"] == "factory_oracle_failed"
            assert result["isolation"]["host_oracle"]["checked"] == 0
    finally:
        for task in (worker, supervisor):
            if not task.done():
                task.cancel()
        await asyncio.gather(worker, supervisor, return_exceptions=True)


@pytest.mark.parametrize(
    "cases", [[], [{"name": "wrong", "input": {"value": 2}, "expected": {"value": True}}]]
)
async def test_invalid_operator_vectors_never_become_review_plans(durable, factory_verifier, cases):
    from caliburn.tool_factory.service import FactoryDenied

    with pytest.raises((ValidationError, FactoryDenied)):
        await plan(durable, factory_verifier[2], oracle_cases=cases)
