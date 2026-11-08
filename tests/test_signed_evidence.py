"""Public-key integrity is real; qualification still remains incomplete/nonexecutable."""

import asyncio
import copy
import json
import os
import secrets
import subprocess
import sys
import time
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from test_factory import AUTH, Scripted, proposal
from test_factory_execution import IMAGE, approved_worker, plan

from caliburn.app import app
from caliburn.runtime.contracts import Submit
from caliburn.runtime.store import NotFound
from caliburn.runtime.worker import Worker
from caliburn.sandbox.contracts import Bundle
from caliburn.sandbox.control import Supervisor
from caliburn.tool_factory.artifact_integrity import (
    ArtifactDenied,
    EvidenceStatement,
    admission,
    key_id,
    parse,
    sign,
    verify,
)
from caliburn.tool_factory.contracts import digest
from caliburn.tool_factory.execution_control import FactoryTestExecutor
from caliburn.tool_factory.execution_queue import ExecutionQueue
from caliburn.tool_factory.registry import POLICY_DIGEST, ArtifactRegistry
from caliburn.tool_factory.schema import exec_jobs, signed_artifacts


def synthetic_statement(private):
    """Unit crypto fixture only: this is never submitted as real platform evidence."""
    bundle = proposal().model_dump()["bundle"]
    bid, rid, req, jid, _pid = [str(uuid4()) for _ in range(5)]
    bh = digest(bundle)
    report = {
        "bundle_sha256": bh,
        "checker_sha256": "0" * 64,
        "classification": "REVIEW_REQUIRED",
        "source_executed": False,
        "activation_eligible": False,
        "execution": "NOT_RUN",
        "security": "INCOMPLETE",
        "dependencies": "UNVERIFIED",
        "license": "UNREVIEWED",
        "findings": [],
        "truncated": False,
    }
    files = {"test_unit.py": "# SYNTHETIC CRYPTO UNIT FIXTURE; NOT EXECUTED\n"}
    binding = {
        "scope": "factory_sandbox_test_only",
        "actor": "development-service",
        "tenant": "development",
        "bundle_ref": bid,
        "bundle_sha256": bh,
        "report_ref": rid,
        "report_sha256": digest(report),
        "source_sha256": Bundle(files=bundle["sources"]).digest(),
        "plan_sha256": Bundle(files=files).digest(),
        "image_digest": "sha256:" + "0" * 64,
        "unit_test_synthetic": True,
    }
    proof = {
        "ok": True,
        "data": {
            "executor_role": "synthetic_executor",
            "request_ref": req,
            "binding_sha256": digest(binding),
            "image_digest": binding["image_digest"],
            "run": {
                "status": "PASSED",
                "exit_code": 0,
                "output": "SYNTHETIC UNIT CRYPTO FIXTURE, NOT EXECUTION EVIDENCE",
                "truncated": False,
                "source_sha256": binding["source_sha256"],
                "plan_sha256": binding["plan_sha256"],
            },
            "source_executed": True,
            "production_approved": False,
            "security": "INCOMPLETE",
            "license": "UNREVIEWED",
        },
        "error": None,
        "isolation": {},
    }
    return EvidenceStatement(
        schema_version="caliburn-evidence-v1",
        purpose="EVIDENCE_ONLY",
        actor="development-service",
        tenant="development",
        key_id=key_id(private.public_key().public_bytes_raw()),
        signer_role="synthetic_signer",
        artifact_policy_sha256=POLICY_DIGEST,
        issued_at=int(time.time()) - 1,
        expires_at=int(time.time()) + 100,
        bundle_ref=bid,
        bundle_sha256=bh,
        bundle=bundle,
        static_report_ref=rid,
        static_report_sha256=digest(report),
        static_report=report,
        execution_job_ref=jid,
        execution_binding_sha256=digest(binding),
        execution_binding=binding,
        execution_result_sha256=digest(proof),
        execution_result=proof,
        decision={"request_id": req, "decision": "APPROVE", "binding_sha256": digest(binding)},
        plan_files=files,
        production_approved=False,
    )


@pytest.mark.parametrize(
    "tamper",
    ["signature", "payload", "key", "scope", "expired", "activation", "duplicate", "algorithm"],
)
def test_crypto_integrity_deny(tamper):
    private = Ed25519PrivateKey.generate()
    statement = synthetic_statement(private)
    envelope = sign(statement, private).model_dump()
    raw = private.public_key().public_bytes_raw()
    verified = verify(
        envelope, raw, actor=statement.actor, tenant=statement.tenant, now=time.time()
    )
    assert not admission(verified)["activation_eligible"]
    value = copy.deepcopy(envelope)
    if tamper == "signature":
        value["signature_hex"] = "0" * 128
    elif tamper == "payload":
        value["statement"]["artifact_policy_sha256"] = "f" * 64
        value["statement_sha256"] = digest(value["statement"])
    elif tamper == "key":
        raw = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
    elif tamper == "scope":
        value["statement"]["tenant"] = "other"
    elif tamper == "expired":
        with pytest.raises(ArtifactDenied):
            verify(
                value, raw, actor=statement.actor, tenant=statement.tenant, now=statement.expires_at
            )
        return
    elif tamper == "activation":
        value["statement"]["production_approved"] = True
    elif tamper == "algorithm":
        value["algorithm"] = "none"
    else:
        raw_json = (
            json.dumps(value)
            .encode()
            .replace(
                b'{"algorithm": "Ed25519",', b'{"algorithm":"Ed25519","algorithm":"Ed25519",', 1
            )
        )
        with pytest.raises(ArtifactDenied):
            parse(raw_json)
        return
    with pytest.raises(ArtifactDenied):
        verify(value, raw, actor=statement.actor, tenant=statement.tenant, now=time.time())


async def completed(durable, verifier_store, reviewer, executor_store, *, bad=False):
    if not IMAGE:
        pytest.skip("Set CALIBURN_REVIEWED_TEST_IMAGE for real signed evidence provenance")
    value = proposal().model_copy(deep=True)
    if bad:
        value.bundle.sources["double.py"] = "def run(value): return {'value':value*3}\n"
    pid = await plan(durable, verifier_store, value=value)
    tid, req, worker = await approved_worker(durable, reviewer, pid)
    try:
        assert await Supervisor(
            ExecutionQueue(executor_store), FactoryTestExecutor(IMAGE)
        ).run_once()
        await asyncio.wait_for(worker, 10)
    finally:
        if not worker.done():
            worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
    with durable.engine.connect() as c:
        jid = c.scalar(select(exec_jobs.c.id))
    return tid, req, jid


async def test_real_signer_process_public_lookup_and_import(
    durable, factory_verifier, factory_execution_authority, artifact_signer, tmp_path
):
    owner, signer, private, kid, signer_store, _ = artifact_signer
    _, reviewer, executor_store, _ = factory_execution_authority
    _, _, jid = await completed(durable, factory_verifier[2], reviewer, executor_store)
    password = secrets.token_urlsafe(32)
    pem = private.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password.encode()),
    )
    keyfile = tmp_path / "ephemeral-encrypted-key.pem"
    keyfile.write_bytes(pem)
    result = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "caliburn.tool_factory.signing_control",
        "--publish-job",
        jid,
        "--private-key",
        str(keyfile),
        env=dict(
            os.environ,
            CALIBURN_DATABASE_URL=signer_store.engine.url.render_as_string(hide_password=False),
            CALIBURN_SIGNING_KEY_PASSWORD=password,
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    out, error = await asyncio.wait_for(result.communicate(), 20)
    assert result.returncode == 0, error.decode()
    assert password.encode() not in out + error
    aid = json.loads(out)["artifact_ref"]
    data = owner.read(aid)
    packet = tmp_path / "signed-evidence.json"
    packet.write_text(json.dumps(data["envelope"]), encoding="utf-8")
    trusted_public = tmp_path / "trusted-public-key.pem"
    trusted_public.write_bytes(
        private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    )
    portable = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "caliburn.tool_factory.signing_control",
        "--verify-envelope",
        str(packet),
        "--trusted-public-key",
        str(trusted_public),
        env=dict(os.environ, CALIBURN_DATABASE_URL="invalid-DSN-intentionally-unused"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    portable_out, portable_error = await asyncio.wait_for(portable.communicate(), 20)
    assert portable.returncode == 0, portable_error.decode()
    assert not json.loads(portable_out)["admission"]["can_invoke"]
    assert not data["admission"]["activation_eligible"]
    assert data["envelope"]["statement"]["key_id"] == kid
    assert signer.publish(jid, private) == aid
    assert signer.import_envelope(parse(json.dumps(data["envelope"]).encode())) == aid
    with TestClient(app) as client:
        route = "/api/v1/capabilities/artifacts/" + aid
        assert client.get(route).status_code == 401
        response = client.get(route, headers=AUTH)
        assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
        assert client.post(route + "/activate", headers=AUTH).status_code == 404
    with pytest.raises(NotFound):
        owner.read(aid, tenant="other")
    task = durable.submit(
        Submit(prompt="Inspect signed evidence from an unrelated task"),
        allow_capability_proposals=True,
    )
    await Worker(
        durable, Scripted("capability_lookup", {"name": "double_integer"}), output_tokens=4096
    ).run_once()
    observed = json.loads(durable.get(task["id"])["result"])
    summary = observed["candidates"][0]["signed_artifacts"][0]
    assert summary["verification_status"] == "VERIFIED_EVIDENCE" and not summary["can_invoke"]


@pytest.mark.parametrize("action", ["key", "signer", "review", "scope", "tamper"])
async def test_registry_live_trust_and_scope_deny(
    durable, factory_verifier, factory_execution_authority, artifact_signer, action
):
    owner, signer, private, kid, _, name = artifact_signer
    _, reviewer, executor_store, _ = factory_execution_authority
    _, req, jid = await completed(durable, factory_verifier[2], reviewer, executor_store)
    aid = signer.publish(jid, private)
    if action == "key":
        owner.revoke_key(kid)
    elif action == "signer":
        owner.disable(name)
    elif action == "review":
        reviewer.revoke(req["id"])
    elif action == "scope":
        with pytest.raises(NotFound):
            owner.read(aid, actor="other")
        return
    else:
        # Even the owner cannot mutate a sealed artifact.
        with pytest.raises(DBAPIError), durable.engine.begin() as c:
            c.execute(
                update(signed_artifacts).where(signed_artifacts.c.id == aid).values(sha256="0" * 64)
            )
        return
    with pytest.raises(ArtifactDenied):
        owner.read(aid)
    with durable.engine.connect() as c:
        bid = c.scalar(select(signed_artifacts.c.bundle_id).where(signed_artifacts.c.id == aid))
        summary = owner.summaries(c, bid, "development-service", "development")[0]
    assert summary["verification_status"] == "UNTRUSTED" and not summary["activation_eligible"]


async def test_signing_rejects_failed_and_self_authored_evidence(
    durable, factory_verifier, factory_execution_authority, artifact_signer
):
    owner, signer, private, _, _, _ = artifact_signer
    _, reviewer, executor_store, _ = factory_execution_authority
    _, _, jid = await completed(durable, factory_verifier[2], reviewer, executor_store, bad=True)
    with pytest.raises(ArtifactDenied):
        signer.publish(jid, private)
    with pytest.raises(ArtifactDenied):
        owner.publish(jid, private)
    with durable.engine.connect() as c:
        assert not c.scalar(select(signed_artifacts.c.id))


def test_signer_startup_errors_are_sanitized():
    marker = "synthetic-private-config-marker"
    result = subprocess.run(
        [sys.executable, "-m", "caliburn.tool_factory.signing_control", "--export", str(uuid4())],
        env=dict(
            os.environ,
            CALIBURN_DATABASE_URL="postgresql+psycopg://user@localhost:" + marker + "/db",
        ),
        capture_output=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 2 and marker.encode() not in result.stderr + result.stdout


async def test_execution_reviewer_cannot_sign_own_evidence(
    durable, factory_verifier, factory_execution_authority, artifact_signer
):
    owner, _, _, _, _, _ = artifact_signer
    _, reviewer, executor_store, names = factory_execution_authority
    _, _, jid = await completed(durable, factory_verifier[2], reviewer, executor_store)
    private = Ed25519PrivateKey.generate()
    owner.configure(names[0], "signing-reviewer")
    owner.register_key(private.public_key().public_bytes_raw(), names[0])
    with pytest.raises(ArtifactDenied):
        ArtifactRegistry(reviewer.store).publish(jid, private)


async def test_temp_map_cannot_restore_disabled_signer(
    durable, factory_verifier, factory_execution_authority, artifact_signer
):
    owner, signer, private, kid, store, name = artifact_signer
    _, reviewer, executor_store, _ = factory_execution_authority
    _, _, jid = await completed(durable, factory_verifier[2], reviewer, executor_store)
    with durable.engine.connect() as c:
        facts, _ = owner.snapshot(c, jid)
        now = int(durable.now(c))
    statement = EvidenceStatement(
        schema_version="caliburn-evidence-v1",
        purpose="EVIDENCE_ONLY",
        key_id=kid,
        signer_role=name,
        artifact_policy_sha256=POLICY_DIGEST,
        issued_at=now,
        expires_at=now + 60,
        production_approved=False,
        **facts,
    )
    envelope = sign(statement, private)
    owner.disable(name)
    with store.engine.begin() as c:
        schema = c.scalar(text("SELECT current_schema()"))
        c.execute(
            text(
                f'CREATE TEMP TABLE factory_registry_roles AS SELECT * FROM "{schema}".factory_registry_roles WHERE false'
            )
        )
        c.execute(
            text(
                "INSERT INTO pg_temp.factory_registry_roles (db_role,principal,tenant,enabled) VALUES (current_user,'forged-signer','development','yes')"
            )
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            signer._insert(c, envelope)
