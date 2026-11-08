"""Actual approved release -> new task -> isolated invocation/reuse; model fixture."""

import asyncio
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select, text
from test_factory import Scripted, proposal
from test_factory_checks import until
from test_factory_execution import IMAGE, ExecutionModel, plan, waiting

from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import LostLease, Store
from caliburn.runtime.worker import Worker
from caliburn.sandbox.control import Supervisor
from caliburn.tool_factory.execution_control import FactoryTestExecutor
from caliburn.tool_factory.execution_queue import ExecutionQueue
from caliburn.tool_factory.release_contracts import ReleaseDenied, profile
from caliburn.tool_factory.release_control import ReleasedExecutor
from caliburn.tool_factory.release_queue import InvocationQueue
from caliburn.tool_factory.release_service import ReleaseService
from caliburn.tool_factory.schema import exec_jobs, release_invocations


@pytest.fixture
def release_authority(durable, artifact_signer):
    owner = ReleaseService(durable)
    _, _, private, _, signer_store, signer_name = artifact_signer
    names = ["release_review_fixture_" + uuid4().hex, "release_invoke_fixture_" + uuid4().hex]
    stores = []
    with durable.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        for name in names:
            c.execute(text(f'CREATE ROLE "{name}" NOLOGIN'))
    for name, kind in zip(names, ("REVIEWER", "EXECUTOR"), strict=True):
        owner.configure(name, "synthetic-release-" + kind.lower(), kind)
        url = durable.engine.url.update_query_dict(
            {"options": f"-csearch_path={schema} -crole={name}"}
        )
        stores.append(Store(url.render_as_string(hide_password=False)))
    owner.configure(signer_name, "synthetic-artifact-signer", "SIGNER")
    yield owner, ReleaseService(stores[0]), stores[1], ReleaseService(signer_store), private
    for store in stores:
        store.engine.dispose()
    with durable.engine.begin() as c:
        for name in names:
            c.execute(text(f'REVOKE ALL ON ALL TABLES IN SCHEMA "{schema}" FROM "{name}"'))
            c.execute(
                text(
                    f'REVOKE UPDATE (state,attempts,lease_token,lease_until,executor_role,result,result_sha256) ON registry_invocations FROM "{name}"'
                )
            )
            c.execute(text(f'REVOKE ALL ON SCHEMA "{schema}" FROM "{name}"'))
            c.execute(text(f'DROP ROLE "{name}"'))


async def artifact(
    store, verifier, reviewer, executor_store, signer, private, version="1.0.0", bad=False
):
    value = proposal().model_copy(deep=True)
    value.bundle.declared_license = "LicenseRef-Proprietary"
    value.bundle.manifest.version = version
    if bad:
        value.bundle.sources["double.py"] = (
            "def run(value):\n    if value == 13: return {'value':'bad'}\n    return {'value': value*2}\n"
        )
    cases = [
        {"name": "two", "input": {"value": 2}, "expected": {"value": 4}},
        {"name": "five", "input": {"value": 5}, "expected": {"value": 10}},
    ]
    pid = await plan(store, verifier, value=value, oracle_cases=cases)
    tid, req = await waiting(store, pid)
    reviewer.decide(req["id"], req["sha256"], "APPROVE")
    worker = asyncio.create_task(Worker(store, ExecutionModel(pid), output_tokens=4096).run_once())
    await until(lambda: execution_exists(store, tid))
    assert await Supervisor(ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)).run_once()
    await asyncio.wait_for(worker, 20)
    with store.engine.connect() as c:
        jid = c.scalar(select(exec_jobs.c.id).where(exec_jobs.c.task_id == tid))
    return signer.publish(jid, private)


def execution_exists(store, tid):
    with store.engine.connect() as c:
        return bool(c.scalar(select(exec_jobs.c.id).where(exec_jobs.c.task_id == tid)))


async def released(
    durable,
    factory_verifier,
    factory_execution_authority,
    artifact_signer,
    release_authority,
    version="1.0.0",
    bad=False,
):
    _, source_reviewer, source_executor, _ = factory_execution_authority
    _, evidence_signer, private, _, _, _ = artifact_signer
    aid = await artifact(
        durable,
        factory_verifier[2],
        source_reviewer,
        source_executor,
        evidence_signer,
        private,
        version,
        bad,
    )
    owner, reviewer, _, signer, private = release_authority
    rid = owner.request(aid)
    with pytest.raises(ReleaseDenied):
        signer.activate(rid, private)
    body = owner.inspect(rid)
    reviewer.decide(rid, body["sha256"], "APPROVE", internal_license_approved=True)
    return signer.activate(rid, private)


async def invoke(store, executor_store, value):
    task = store.submit(
        Submit(prompt="Reuse independently released double tool"), allow_registry_invocation=True
    )
    assert task["policy"]["capabilities"]["double_integer"]["release_id"]
    worker = asyncio.create_task(
        Worker(store, Scripted("double_integer", {"value": value}), output_tokens=4096).run_once()
    )
    await until(lambda: count_pending(store, task["id"]) == 1)
    assert await Supervisor(InvocationQueue(executor_store), ReleasedExecutor(IMAGE)).run_once()
    await asyncio.wait_for(worker, 20)
    return store.get(task["id"])


def count_pending(store, tid):
    with store.engine.connect() as c:
        return c.scalar(
            select(func.count())
            .select_from(release_invocations)
            .where(release_invocations.c.task_id == tid)
        )


async def test_release_and_reuse_across_tasks(
    durable,
    factory_verifier,
    factory_execution_authority,
    artifact_signer,
    release_authority,
    monkeypatch,
):
    if not IMAGE:
        pytest.skip("Actual property/invocation image required")
    vid = await released(
        durable, factory_verifier, factory_execution_authority, artifact_signer, release_authority
    )
    owner, _, executor, _, _ = release_authority
    assert owner.active()[0]["release_ref"] == vid
    first = await invoke(durable, executor, 7)
    second = await invoke(durable, executor, 11)
    assert first["state"] == second["state"] == "COMPLETED"
    assert '"value": 14' in first["result"] and '"value": 22' in second["result"]
    assert first["id"] != second["id"]
    metrics = owner.metrics()[0]
    assert metrics["invocations"] == 2
    from caliburn.app import app
    from caliburn.config import get_settings

    monkeypatch.setenv("CALIBURN_ALLOW_REGISTRY_INVOCATION", "true")
    get_settings.cache_clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (await client.get("/api/v1/registry")).status_code == 401
        headers = {"Authorization": "Bearer test-service-token-secret"}
        catalog = await client.get("/api/v1/registry", headers=headers)
        assert catalog.status_code == 200
        assert catalog.json()["tools"][0]["release_ref"] == vid
        assert catalog.headers["cache-control"] == "no-store"
        assert (await client.get("/api/v1/registry/metrics", headers=headers)).status_code == 200
        submitted = await client.post(
            "/api/v1/tasks",
            headers=headers,
            json={
                "prompt": "Aggregate with the registered tool",
                "capabilities": ["double_integer"],
            },
        )
        assert submitted.status_code in (200, 202)
        assert (
            durable.get(submitted.json()["id"])["policy"]["capabilities"]["double_integer"][
                "release_id"
            ]
            == vid
        )
    with durable.engine.connect() as c:
        assert (
            c.scalar(
                select(func.count())
                .select_from(release_invocations)
                .where(release_invocations.c.release_id == vid)
            )
            == 2
        )


async def test_version_pin_rollback_revoke(
    durable, factory_verifier, factory_execution_authority, artifact_signer, release_authority
):
    if not IMAGE:
        pytest.skip("Actual property/invocation image required")
    args = (
        durable,
        factory_verifier,
        factory_execution_authority,
        artifact_signer,
        release_authority,
    )
    first = await released(*args)
    pinned = durable.submit(Submit(prompt="Keep original version"), allow_registry_invocation=True)
    durable.control(pinned["id"], "pause")
    second = await released(*args, version="1.0.1")
    owner = release_authority[0]
    assert owner.active()[0]["release_ref"] == second
    with durable.engine.connect() as c:
        assert owner.authorize(c, pinned, "double_integer")[0]["id"] == first
    owner.rollback(first)
    assert owner.active()[0]["release_ref"] == first
    owner.revoke(first)
    assert owner.active() == []
    with durable.engine.connect() as c, pytest.raises(ReleaseDenied):
        owner.authorize(c, pinned, "double_integer")
    with pytest.raises(ReleaseDenied):
        durable.submit(
            Submit(prompt="Unavailable", capabilities=["double_integer"]),
            allow_registry_invocation=True,
        )


async def test_bad_output_quarantines_release(
    durable, factory_verifier, factory_execution_authority, artifact_signer, release_authority
):
    if not IMAGE:
        pytest.skip("Actual property/invocation image required")
    vid = await released(
        durable,
        factory_verifier,
        factory_execution_authority,
        artifact_signer,
        release_authority,
        bad=True,
    )
    task = await invoke(durable, release_authority[2], 13)
    assert task["state"] == "FAILED"
    assert release_authority[0].active() == []
    with durable.engine.connect() as c:
        row = (
            c.execute(select(release_invocations).where(release_invocations.c.release_id == vid))
            .mappings()
            .one()
        )
    assert row["result"]["ok"] is False
    assert row["result"]["error"] == "output_schema_failed"


async def test_executor_recovery_fences_old_nonce_and_cancel(
    durable, factory_verifier, factory_execution_authority, artifact_signer, release_authority
):
    if not IMAGE:
        pytest.skip("Actual property/invocation image required")
    await released(
        durable, factory_verifier, factory_execution_authority, artifact_signer, release_authority
    )
    task = durable.submit(Submit(prompt="Recover registered tool"), allow_registry_invocation=True)
    worker = asyncio.create_task(
        Worker(durable, Scripted("double_integer", {"value": 7}), output_tokens=4096).run_once()
    )
    await until(lambda: count_pending(durable, task["id"]) == 1)
    q = InvocationQueue(release_authority[2])
    old = q.claim(IMAGE)
    assert old and q.claim(IMAGE) is None
    # Actual DB-clock lease expiry; do not bypass immutable receipt guards.
    await asyncio.sleep(15.2)
    recovered = q.claim(IMAGE)
    assert recovered and old["lease_token"] != recovered["lease_token"]
    assert not q.heartbeat(old)
    from caliburn.sandbox.contracts import Result

    with pytest.raises(LostLease):
        q.finish(old, Result(ok=True, data={"values": [{"value": 14}]}))
    durable.control(task["id"], "cancel")
    assert not q.heartbeat(recovered)
    with pytest.raises(LostLease):
        q.finish(recovered, Result(ok=True, data={"values": [{"value": 14}]}))
    await asyncio.wait_for(worker, 20)
    assert durable.get(task["id"])["state"] == "CANCELLED"


@pytest.mark.parametrize(
    "code",
    [
        "import os\ndef run(value): return {'value':value}\n",
        "def run(value):\n    return {'value':eval(value)}\n",
        "def run(value):\n    return {'value':value.real}\n",
    ],
)
def test_pure_json_profile_rejects_host_capability_paths(code):
    value = proposal().model_dump()["bundle"]
    value["declared_license"] = "LicenseRef-Proprietary"
    value["sources"]["double.py"] = code
    with pytest.raises(ReleaseDenied):
        profile(value)
