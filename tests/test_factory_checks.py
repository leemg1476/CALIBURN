"""Independent static triage: real PostgreSQL roles/queue, no candidate execution."""

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import DBAPIError
from test_factory import AUTH, Scripted, call, count, proposal, started

from caliburn.app import app
from caliburn.config import get_settings
from caliburn.runtime.contracts import Submit
from caliburn.runtime.schema import tasks
from caliburn.runtime.store import LostLease, NotFound
from caliburn.runtime.worker import Worker
from caliburn.tool_factory.checks import CheckQueue, VerifierAuthority
from caliburn.tool_factory.contracts import CHECKER_DIGEST, CheckArgs, StaticReport, digest
from caliburn.tool_factory.schema import check_jobs, check_reports, verifiers
from caliburn.tool_factory.service import Factory, FactoryDenied
from caliburn.tool_factory.static_check import analyze


def candidate(store, value=None):
    value = value or proposal()
    tid, token, sid = started(store, value)
    result = Factory(store).propose(tid, token, sid, value)
    store.control(tid, "cancel")
    return result["id"]


def pending(store, bundle_id=None, **limits):
    bundle_id = bundle_id or candidate(store)
    task = store.submit(
        Submit(prompt="Independently check candidate", limits=limits), allow_capability_checks=True
    )
    claimed = store.claim("fixture-check-worker", 30)
    assert claimed["id"] == task["id"]
    args = CheckArgs(bundle_ref=bundle_id)
    step = store.prepare(
        task["id"], claimed["lease_token"], "TOOL", call("capability_check", args.model_dump())
    )
    job = CheckQueue(store).submit(task["id"], claimed["lease_token"], step["id"], args)
    return task["id"], claimed["lease_token"], step["id"], job


async def until(predicate):
    async with asyncio.timeout(10):
        while not predicate():
            await asyncio.sleep(0.01)


def test_static_triage_is_bounded_and_never_a_pass(tmp_path):
    value = proposal().model_dump()["bundle"]
    clean = analyze(value, CHECKER_DIGEST)
    assert StaticReport.model_validate(clean).classification == "REVIEW_REQUIRED"
    assert not clean["activation_eligible"] and not clean["source_executed"]
    marker = tmp_path / "never-executed"
    value["sources"]["double.py"] = (
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n"
    )
    blocked = analyze(value, CHECKER_DIGEST)
    assert blocked["classification"] == "BLOCKED" and not marker.exists()
    assert any(item["code"] == "dynamic_or_io_call" for item in blocked["findings"])
    value["sources"]["double.py"] = "def invalid(\n"
    assert analyze(value, CHECKER_DIGEST)["findings"][0]["code"] == "invalid_python_syntax"
    value["sources"]["double.py"] = "\n".join(f"open('x{i}')" for i in range(200))
    bounded = analyze(value, CHECKER_DIGEST)
    assert len(bounded["findings"]) == 128 and bounded["truncated"]
    with pytest.raises(ValidationError):
        StaticReport.model_validate(clean | {"classification": "PASS"})


def test_startup_diagnostics_do_not_echo_invalid_config():
    marker = "fixture-private-port-marker"
    result = subprocess.run(
        [sys.executable, "-m", "caliburn.tool_factory.verifier", "--once"],
        env=dict(
            os.environ,
            CALIBURN_DATABASE_URL="postgresql+psycopg://user@127.0.0.1:" + marker + "/db",
        ),
        capture_output=True,
        check=False,
        text=True,
        timeout=15,
    )
    assert result.returncode == 2
    assert marker not in result.stderr + result.stdout
    assert result.stderr == "Static verifier failed; no candidate executed\n"


async def test_real_worker_separate_verifier_and_scoped_api(durable, factory_verifier):
    _, authority, verifier_store, _ = factory_verifier
    cid = candidate(durable)
    task = durable.submit(
        Submit(prompt="Check earlier task artifact"), allow_capability_checks=True
    )
    worker = asyncio.create_task(
        Worker(
            durable, Scripted("capability_check", {"bundle_ref": cid}), output_tokens=4096
        ).run_once()
    )
    try:
        await until(lambda: count(durable, check_jobs) == 1)
        assert not worker.done()
        # Actual isolated process with verifier DB-role connection; no shared Python object.
        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "caliburn.tool_factory.verifier",
            "--once",
            env=dict(
                os.environ,
                CALIBURN_DATABASE_URL=verifier_store.engine.url.render_as_string(
                    hide_password=False
                ),
            ),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        _, error = await asyncio.wait_for(proc.communicate(), 20)
        assert proc.returncode == 0, error.decode()
        await asyncio.wait_for(worker, 10)
    finally:
        if not worker.done():
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)
    result = durable.get(task["id"])
    assert result["state"] == "COMPLETED"
    data = json.loads(result["result"])
    assert data["report"]["classification"] == "REVIEW_REQUIRED"
    assert not data["report"]["source_executed"]
    assert count(durable, check_reports) == 1
    with TestClient(app) as client:
        route = "/api/v1/capabilities/reports/" + data["report_ref"]
        assert client.get(route).status_code == 401
        view = client.get(route, headers=AUTH)
        assert view.status_code == 200 and view.json()["verifier_role"] != "postgres"
        assert client.post(route + "/approve", headers=AUTH).status_code == 404
    with pytest.raises(NotFound):
        CheckQueue(durable).read(data["report_ref"], tenant="other")
    assert authority.claim() is None


def test_recovery_stale_verifier_and_report_immutability(durable, factory_verifier):
    _, verifier, _, _ = factory_verifier
    tid, _token, sid, jid = pending(durable)
    first = verifier.claim(0.1)
    with verifier.store.engine.begin() as c:
        c.execute(
            update(check_jobs).where(check_jobs.c.id == jid).values(lease_until=durable.now(c) - 1)
        )
    second = verifier.claim()
    with pytest.raises(FactoryDenied):
        verifier.finish(jid, first["lease_token"], analyze(first["payload"], CHECKER_DIGEST))
    report_id = verifier.finish(
        jid, second["lease_token"], analyze(second["payload"], CHECKER_DIGEST)
    )
    for statement in (
        update(check_reports).values(body_sha256="0" * 64),
        update(check_jobs).values(bundle_sha256="0" * 64),
    ):
        with pytest.raises(DBAPIError), durable.engine.begin() as c:
            c.execute(statement)
    with durable.engine.begin() as c:
        c.execute(update(tasks).where(tasks.c.id == tid).values(lease_until=durable.now(c) - 1))
    replacement = durable.claim("replacement", 30)
    args = CheckArgs(bundle_ref=second["bundle_id"])
    assert CheckQueue(durable).submit(tid, replacement["lease_token"], sid, args) == jid
    result = CheckQueue(durable).result(tid, replacement["lease_token"], jid)
    assert result["report_ref"] == report_id and count(durable, check_jobs) == 1
    assert count(durable, check_reports) == 1


@pytest.mark.parametrize("action", ["cancel", "pause", "deadline", "revoke"])
def test_no_publication_after_stop_or_offboarding(durable, factory_verifier, action):
    owner, verifier, _, name = factory_verifier
    tid, _, _, jid = pending(durable)
    job = verifier.claim()
    if action in {"cancel", "pause"}:
        durable.control(tid, action)
    elif action == "deadline":
        with durable.engine.begin() as c:
            c.execute(update(tasks).where(tasks.c.id == tid).values(deadline=durable.now(c) - 1))
    else:
        owner.disable(name)
    with pytest.raises(FactoryDenied):
        verifier.finish(jid, job["lease_token"], analyze(job["payload"], CHECKER_DIGEST))
    assert count(durable, check_reports) == 0


def test_self_attestation_and_forgery_denied(durable, factory_verifier):
    _, verifier, _, _ = factory_verifier
    _, _, _, jid = pending(durable)
    with pytest.raises(FactoryDenied):
        VerifierAuthority(durable).claim()
    job = verifier.claim()
    body = analyze(job["payload"], CHECKER_DIGEST)
    for altered in (body | {"bundle_sha256": "0" * 64}, body | {"checker_sha256": "0" * 64}):
        with pytest.raises(FactoryDenied):
            verifier.finish(jid, job["lease_token"], altered)
    with pytest.raises(DBAPIError), durable.engine.begin() as c:
        c.execute(
            insert(check_reports).values(
                id=str(uuid4()),
                job_id=jid,
                lease_token=job["lease_token"],
                verifier_role="forged",
                body=body,
                body_sha256=digest(body),
                created_at=durable.now(c),
            )
        )
    with durable.engine.begin() as c:
        c.execute(
            insert(verifiers).values(
                db_role="postgres", principal="self", tenant="development", enabled="yes"
            )
        )
    with verifier.store.engine.begin() as c:
        c.execute(
            update(check_jobs).where(check_jobs.c.id == jid).values(lease_until=durable.now(c) - 1)
        )
    with pytest.raises(FactoryDenied):
        VerifierAuthority(durable).claim()
    assert count(durable, check_reports) == 0


def test_claim_contention_and_paused_job_does_not_starve(durable, factory_verifier):
    _, verifier, _, _ = factory_verifier
    cid = candidate(durable)
    a = pending(durable, cid)
    durable.control(a[0], "pause")
    b = pending(durable, cid)
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda _: verifier.claim(), range(2)))
    claimed = [job for job in claims if job]
    assert len(claimed) == 1 and claimed[0]["id"] == b[3]


async def test_disabled_policy_timeout_and_queue_receipt(durable, monkeypatch):
    cid = candidate(durable)
    task = durable.submit(Submit(prompt="No static check grant"), allow_capability_proposals=True)
    await Worker(
        durable, Scripted("capability_check", {"bundle_ref": cid}), output_tokens=4096
    ).run_once()
    assert durable.get(task["id"])["error"] == "tool_policy_denied"
    monkeypatch.setenv("CALIBURN_ALLOW_CAPABILITY_CHECKS", "true")
    get_settings.cache_clear()
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks",
            json={"prompt": "Wait without verifier", "limits": {"call_timeout_seconds": 0.1}},
            headers=AUTH,
        )
        assert response.status_code == 202
    tid = response.json()["id"]
    await Worker(
        durable, Scripted("capability_check", {"bundle_ref": cid}), output_tokens=4096
    ).run_once()
    assert durable.get(tid)["state"] == "TIMED_OUT"
    assert count(durable, check_jobs) == 1 and count(durable, check_reports) == 0


def test_sqlite_verifier_denied(durable):
    if durable.engine.dialect.name != "sqlite":
        pytest.skip("SQLite denial only")
    with pytest.raises(FactoryDenied):
        VerifierAuthority(durable).claim()


def test_receipt_input_scope_and_request_budget(durable):
    tid, token, sid, jid = pending(durable)
    with durable.engine.connect() as c:
        job = c.execute(select(check_jobs).where(check_jobs.c.id == jid)).mappings().one()
    args = CheckArgs(bundle_ref=job["bundle_id"])
    assert CheckQueue(durable).submit(tid, token, sid, args) == jid
    with pytest.raises(FactoryDenied):
        CheckQueue(durable).submit(tid, token, sid, CheckArgs(bundle_ref=str(uuid4())))
    assert count(durable, check_jobs) == 1
    assert len([e for e in durable.replay(tid) if e["type"] == "CAPABILITY_CHECK_REQUESTED"]) == 1
    durable.control(tid, "cancel")
    with pytest.raises(LostLease):
        CheckQueue(durable).submit(tid, token, sid, args)
    other = durable.submit(
        Submit(prompt="other scope"), actor="other", allow_capability_checks=True
    )
    claimed = durable.claim("other", 30)
    step = durable.prepare(
        other["id"], claimed["lease_token"], "TOOL", call("capability_check", args.model_dump())
    )
    with pytest.raises(FactoryDenied):
        CheckQueue(durable).submit(other["id"], claimed["lease_token"], step["id"], args)


@pytest.mark.parametrize("change", ["attempts", "revision", "ended"])
def test_retry_revision_and_ended_request_fail_closed(durable, factory_verifier, change):
    _, verifier, _, _ = factory_verifier
    tid, _, _, jid = pending(durable)
    if change == "ended":
        durable.control(tid, "cancel")
    elif change == "revision":
        # Owner bypass would also invalidate immutable input. Use a future checker process
        # identity mismatch, without modifying the bound queue request.
        from unittest.mock import patch

        from caliburn.tool_factory import checks

        with patch.object(checks, "CHECKER_DIGEST", "0" * 64):
            assert verifier.claim() is None
    else:
        for _ in range(3):
            job = verifier.claim()
            with verifier.store.engine.begin() as c:
                c.execute(
                    update(check_jobs)
                    .where(check_jobs.c.id == jid)
                    .values(lease_until=durable.now(c) - 1)
                )
            assert job
    assert verifier.claim() is None
    with durable.engine.connect() as c:
        state = c.scalar(select(check_jobs.c.state).where(check_jobs.c.id == jid))
    assert state in {"FAILED", "CANCELLED"}
    assert count(durable, check_reports) == 0


def test_sql_cannot_turn_static_report_into_execution_proof(durable, factory_verifier):
    _, verifier, store, _ = factory_verifier
    _, _, _, jid = pending(durable)
    job = verifier.claim()
    body = analyze(job["payload"], CHECKER_DIGEST)
    for patch in (
        {"source_executed": True},
        {"activation_eligible": True},
        {"classification": "PASS"},
        {"security": "VERIFIED"},
        {"dependencies": "VERIFIED"},
    ):
        altered = body | patch
        with pytest.raises(DBAPIError), store.engine.begin() as c:
            c.execute(
                insert(check_reports).values(
                    id=str(uuid4()),
                    job_id=jid,
                    lease_token=job["lease_token"],
                    verifier_role="fake",
                    body=altered,
                    body_sha256=digest(altered),
                    created_at=durable.now(c),
                )
            )
    assert verifier.finish(jid, job["lease_token"], body)
    with pytest.raises(DBAPIError), store.engine.begin() as c:
        c.execute(update(tasks).values(state="COMPLETED"))


def test_checker_role_tenant_scope(durable, factory_verifier):
    _, verifier, _, name = factory_verifier
    pending(durable)
    with durable.engine.begin() as c:
        c.execute(update(verifiers).where(verifiers.c.db_role == name).values(tenant="other"))
    assert verifier.claim() is None


def test_verifier_runtime_privilege_expansion_invalidates_authority(durable, factory_verifier):
    owner, verifier, _, name = factory_verifier
    with durable.engine.begin() as c:
        c.execute(text(f'GRANT INSERT ON runtime_tasks TO "{name}"'))
    with pytest.raises(FactoryDenied):
        owner.configure(name, "synthetic-independent-verifier")
    with pytest.raises(FactoryDenied):
        verifier.claim()


def test_temp_mapping_cannot_restore_static_verifier(durable, factory_verifier):
    owner, verifier, store, name = factory_verifier
    _, _, _, jid = pending(durable)
    job = verifier.claim()
    owner.disable(name)
    body = analyze(job["payload"], CHECKER_DIGEST)
    with store.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(
            text(
                f'CREATE TEMP TABLE factory_verifiers AS SELECT * FROM "{schema}".factory_verifiers WHERE false'
            )
        )
        c.execute(
            text(
                "INSERT INTO pg_temp.factory_verifiers (db_role,principal,tenant,enabled) VALUES (current_user,'forged-static-service','development','yes')"
            )
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            c.execute(
                insert(check_reports).values(
                    id=str(uuid4()),
                    job_id=jid,
                    lease_token=job["lease_token"],
                    verifier_role=name,
                    body=body,
                    body_sha256=digest(body),
                    created_at=durable.now(c),
                )
            )
    assert count(durable, check_reports) == 0


async def test_tool_budget_blocks_job_creation(durable):
    cid = candidate(durable)
    task = durable.submit(
        Submit(prompt="zero tool budget", limits={"max_tool_calls": 0}),
        allow_capability_checks=True,
    )
    await Worker(
        durable, Scripted("capability_check", {"bundle_ref": cid}), output_tokens=4096
    ).run_once()
    assert durable.get(task["id"])["error"] == "tool_call_limit"
    assert count(durable, check_jobs) == 0
