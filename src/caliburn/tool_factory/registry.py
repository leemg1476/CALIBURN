"""Independent signing and public verification of immutable, nonexecutable evidence."""

import hashlib
import json
import re
from pathlib import Path
from uuid import uuid4

from sqlalchemy import insert, select, text, update
from sqlalchemy.exc import IntegrityError

from caliburn.runtime.redaction import contains_secret
from caliburn.runtime.schema import steps, tasks
from caliburn.runtime.store import NotFound
from caliburn.tool_factory.artifact_integrity import (
    ArtifactDenied,
    EvidenceStatement,
    admission,
    key_id,
    sign,
    verify,
)
from caliburn.tool_factory.checks import VerifierAuthority, mutable_runtime, role
from caliburn.tool_factory.contracts import digest
from caliburn.tool_factory.execution_contracts import ExecutionResult
from caliburn.tool_factory.oracle import require_proof
from caliburn.tool_factory.schema import (
    bundles,
    check_reports,
    exec_decisions,
    exec_jobs,
    exec_plans,
    exec_requests,
    exec_revocations,
    exec_roles,
    registry_roles,
    signed_artifacts,
    signing_keys,
    verifiers,
)

POLICY_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + Path(__file__).with_name("artifact_integrity.py").read_bytes()
    + Path(__file__).with_name("oracle.py").read_bytes()
).hexdigest()


class ArtifactRegistry:
    def __init__(self, store, *, secrets=()):
        self.store, self.secrets = store, secrets

    def configure(self, db_role, principal, tenant="development"):
        if (
            not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", db_role)
            or not 1 <= len(principal) <= 80
            or not 1 <= len(tenant) <= 100
        ):
            raise ValueError("Invalid registry signer")
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            if not c.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:name)"), {"name": db_role}
            ) or mutable_runtime(c, db_role):
                raise ArtifactDenied()
            old = (
                c.execute(select(registry_roles).where(registry_roles.c.db_role == db_role))
                .mappings()
                .first()
            )
            if old and any(
                old[k] != v
                for k, v in {"principal": principal, "tenant": tenant, "enabled": "yes"}.items()
            ):
                raise ArtifactDenied()
            if not old:
                c.execute(
                    insert(registry_roles).values(
                        db_role=db_role, principal=principal, tenant=tenant, enabled="yes"
                    )
                )
            schema = c.scalar(text("SELECT current_schema()")).replace('"', '""')
            c.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{db_role}"'))
            for name in (
                "factory_registry_roles",
                "factory_signing_keys",
                "factory_signed_artifacts",
                "factory_bundles",
                "factory_check_reports",
                "factory_exec_requests",
                "factory_exec_decisions",
                "factory_exec_revocations",
                "factory_exec_roles",
                "factory_exec_plans",
                "factory_exec_jobs",
                "factory_verifiers",
                "runtime_tasks",
                "runtime_steps",
            ):
                c.execute(text(f'GRANT SELECT ON "{schema}".{name} TO "{db_role}"'))
            c.execute(text(f'GRANT INSERT ON "{schema}".factory_signed_artifacts TO "{db_role}"'))

    def disable(self, db_role):
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            c.execute(
                update(registry_roles)
                .where(registry_roles.c.db_role == db_role)
                .values(enabled="no")
            )

    def register_key(self, public_bytes, signer_role, *, ttl_seconds=86400):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 31_536_000:
            raise ValueError("Invalid key TTL")
        fingerprint = key_id(public_bytes)
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            who = (
                c.execute(
                    select(registry_roles).where(
                        registry_roles.c.db_role == signer_role, registry_roles.c.enabled == "yes"
                    )
                )
                .mappings()
                .first()
            )
            if not who:
                raise ArtifactDenied()
            now = int(self.store.now(c))
            old = (
                c.execute(select(signing_keys).where(signing_keys.c.id == fingerprint))
                .mappings()
                .first()
            )
            if old:
                if (
                    old["signer_role"] != signer_role
                    or old["tenant"] != who["tenant"]
                    or old["state"] != "ACTIVE"
                    or old["expires_at"] <= now
                ):
                    raise ArtifactDenied()
                return fingerprint
            c.execute(
                insert(signing_keys).values(
                    id=fingerprint,
                    tenant=who["tenant"],
                    signer_role=signer_role,
                    public_key_hex=public_bytes.hex(),
                    not_before=now,
                    expires_at=now + ttl_seconds,
                    state="ACTIVE",
                )
            )
            return fingerprint

    def revoke_key(self, fingerprint):
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            c.execute(
                update(signing_keys)
                .where(signing_keys.c.id == fingerprint, signing_keys.c.state == "ACTIVE")
                .values(state="REVOKED")
            )

    def _key(self, c, fingerprint, tenant, *, signer=None):
        if c.dialect.name != "postgresql":
            raise ArtifactDenied()
        key = (
            c.execute(
                select(signing_keys).where(
                    signing_keys.c.id == fingerprint, signing_keys.c.tenant == tenant
                )
            )
            .mappings()
            .first()
        )
        who = (
            c.execute(
                select(registry_roles).where(
                    registry_roles.c.db_role == key["signer_role"]
                    if key
                    else registry_roles.c.db_role == "",
                    registry_roles.c.enabled == "yes",
                    registry_roles.c.tenant == tenant,
                )
            )
            .mappings()
            .first()
        )
        now = self.store.now(c)
        if (
            not key
            or not who
            or key["state"] != "ACTIVE"
            or not key["not_before"] <= now < key["expires_at"]
            or (signer is not None and signer != key["signer_role"])
            or mutable_runtime(c, key["signer_role"])
        ):
            raise ArtifactDenied()
        raw = bytes.fromhex(key["public_key_hex"])
        if key_id(raw) != fingerprint:
            raise ArtifactDenied()
        return key, raw, who

    def snapshot(self, c, job_id):
        job = c.execute(select(exec_jobs).where(exec_jobs.c.id == job_id)).mappings().first()
        if (
            not job
            or job["state"] != "COMPLETED"
            or not job["result"]
            or digest(job["result"]) != job["result_sha256"]
        ):
            raise ArtifactDenied()
        result = ExecutionResult.model_validate(job["result"])
        if not result.ok or result.data is None or result.data.run.status != "PASSED":
            raise ArtifactDenied()
        req = (
            c.execute(select(exec_requests).where(exec_requests.c.id == job["request_id"]))
            .mappings()
            .one()
        )
        plan = (
            c.execute(select(exec_plans).where(exec_plans.c.id == req["plan_id"])).mappings().one()
        )
        bundle = (
            c.execute(select(bundles).where(bundles.c.id == plan["bundle_id"])).mappings().one()
        )
        report = (
            c.execute(select(check_reports).where(check_reports.c.id == plan["report_id"]))
            .mappings()
            .one()
        )
        decision = (
            c.execute(select(exec_decisions).where(exec_decisions.c.request_id == req["id"]))
            .mappings()
            .first()
        )
        task = c.execute(select(tasks).where(tasks.c.id == job["task_id"])).mappings().one()
        step = c.execute(select(steps).where(steps.c.id == job["step_id"])).mappings().one()
        if (
            not decision
            or decision["decision"] != "APPROVE"
            or task["state"] != "COMPLETED"
            or step["status"] != "COMPLETED"
            or step["task_id"] != task["id"]
            or req["task_id"] != task["id"]
            or job["tenant"] != task["tenant"]
            or bundle["actor"] != task["actor"]
            or bundle["tenant"] != task["tenant"]
            or plan["actor"] != task["actor"]
            or plan["tenant"] != task["tenant"]
            or job["binding_sha256"] != req["sha256"]
            or digest(req["binding"]) != req["sha256"]
        ):
            raise ArtifactDenied()
        try:
            output = step["output"]
            if (
                output["role"] != "tool"
                or output["name"] != "capability_execute_tests"
                or digest(json.loads(output["content"])) != job["result_sha256"]
            ):
                raise ArtifactDenied()
        except (KeyError, TypeError, ValueError) as exc:
            raise ArtifactDenied() from exc
        if c.execute(
            select(exec_revocations).where(exec_revocations.c.request_id == req["id"])
        ).first():
            raise ArtifactDenied()
        for table, column, name in (
            (verifiers, verifiers.c.db_role, report["verifier_role"]),
            (exec_roles, exec_roles.c.db_role, decision["reviewer_role"]),
            (exec_roles, exec_roles.c.db_role, job["executor_role"]),
        ):
            who = (
                c.execute(
                    select(table).where(
                        column == name, table.c.tenant == task["tenant"], table.c.enabled == "yes"
                    )
                )
                .mappings()
                .first()
            )
            if not who:
                raise ArtifactDenied()
        facts = {
            "actor": task["actor"],
            "tenant": task["tenant"],
            "bundle_ref": bundle["id"],
            "bundle_sha256": bundle["sha256"],
            "bundle": bundle["payload"],
            "static_report_ref": report["id"],
            "static_report_sha256": report["body_sha256"],
            "static_report": report["body"],
            "execution_job_ref": job_id,
            "execution_binding_sha256": req["sha256"],
            "execution_binding": req["binding"],
            "execution_result_sha256": job["result_sha256"],
            "execution_result": job["result"],
            "decision": dict(decision),
            "plan_files": plan["files"],
        }
        authors = {
            bundle["creator_role"],
            req["creator_role"],
            plan["owner_role"],
            report["verifier_role"],
            decision["reviewer_role"],
            job["executor_role"],
        }
        if contains_secret(facts, self.secrets):
            raise ArtifactDenied()
        return facts, authors

    def publish(self, job_id, private_key, *, ttl_seconds=86400):
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 2_592_000:
            raise ValueError("Invalid artifact TTL")
        fingerprint = key_id(private_key.public_key().public_bytes_raw())
        with self.store.engine.begin() as c:
            facts, authors = self.snapshot(c, job_id)
            if (
                require_proof(
                    facts["execution_binding"], facts["execution_result"]["isolation"]
                ).status
                != "PASSED"
            ):
                raise ArtifactDenied()
            key, _, who = self._key(c, fingerprint, facts["tenant"], signer=role(c))
            if role(c) in authors or who["principal"] == facts["actor"]:
                raise ArtifactDenied()
            old = (
                c.execute(
                    select(signed_artifacts).where(
                        signed_artifacts.c.job_id == job_id,
                        signed_artifacts.c.key_id == fingerprint,
                    )
                )
                .mappings()
                .first()
            )
            if old:
                self._verify(c, old)
                return old["id"]
            now = int(self.store.now(c))
            if now < key["not_before"]:
                raise ArtifactDenied()
            statement = EvidenceStatement(
                schema_version="caliburn-evidence-v1",
                purpose="EVIDENCE_ONLY",
                key_id=fingerprint,
                signer_role=role(c),
                artifact_policy_sha256=POLICY_DIGEST,
                issued_at=now,
                expires_at=min(now + ttl_seconds, int(key["expires_at"])),
                production_approved=False,
                **facts,
            )
            envelope = sign(statement, private_key)
            return self._insert(c, envelope)

    def _insert(self, c, envelope):
        statement = envelope.statement
        if (
            require_proof(statement.execution_binding, statement.execution_result.isolation).status
            != "PASSED"
        ):
            raise ArtifactDenied()
        _, raw, who = self._key(c, statement.key_id, statement.tenant, signer=role(c))
        if statement.signer_role != role(c) or who["principal"] == statement.actor:
            raise ArtifactDenied()
        facts, authors = self.snapshot(c, statement.execution_job_ref)
        if role(c) in authors or any(statement.model_dump()[k] != v for k, v in facts.items()):
            raise ArtifactDenied()
        verify(
            envelope.model_dump(),
            raw,
            actor=statement.actor,
            tenant=statement.tenant,
            now=self.store.now(c),
        )
        if statement.expires_at > self._key(c, statement.key_id, statement.tenant)[0]["expires_at"]:
            raise ArtifactDenied()
        aid = str(uuid4())
        values = {
            "id": aid,
            "bundle_id": statement.bundle_ref,
            "job_id": statement.execution_job_ref,
            "key_id": statement.key_id,
            "actor": statement.actor,
            "tenant": statement.tenant,
            "signer_role": statement.signer_role,
            "stage": "EVIDENCE_ONLY",
            "envelope": envelope.model_dump(),
            "sha256": digest(envelope.model_dump()),
            "created_at": self.store.now(c),
            "expires_at": statement.expires_at,
        }
        try:
            with c.begin_nested():
                c.execute(insert(signed_artifacts).values(**values))
            return aid
        except IntegrityError:
            old = (
                c.execute(
                    select(signed_artifacts).where(
                        signed_artifacts.c.job_id == statement.execution_job_ref,
                        signed_artifacts.c.key_id == statement.key_id,
                    )
                )
                .mappings()
                .first()
            )
            if not old or old["sha256"] != values["sha256"]:
                raise ArtifactDenied() from None
            self._verify(c, old)
            return old["id"]

    def import_envelope(self, envelope):
        with self.store.engine.begin() as c:
            return self._insert(c, envelope)

    def _verify(self, c, row):
        _, raw, _ = self._key(c, row["key_id"], row["tenant"], signer=row["signer_role"])
        if digest(row["envelope"]) != row["sha256"] or row["stage"] != "EVIDENCE_ONLY":
            raise ArtifactDenied()
        envelope = verify(
            row["envelope"], raw, actor=row["actor"], tenant=row["tenant"], now=self.store.now(c)
        )
        statement = envelope.statement
        if (
            statement.bundle_ref != row["bundle_id"]
            or statement.execution_job_ref != row["job_id"]
            or statement.signer_role != row["signer_role"]
            or statement.key_id != row["key_id"]
            or statement.expires_at != row["expires_at"]
        ):
            raise ArtifactDenied()
        facts, _ = self.snapshot(c, row["job_id"])
        if any(statement.model_dump()[k] != v for k, v in facts.items()):
            raise ArtifactDenied()
        return envelope

    def read(self, artifact_id, actor="development-service", tenant="development"):
        with self.store.engine.begin() as c:
            row = (
                c.execute(
                    select(signed_artifacts).where(
                        signed_artifacts.c.id == artifact_id,
                        signed_artifacts.c.actor == actor,
                        signed_artifacts.c.tenant == tenant,
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound()
            envelope = self._verify(c, row)
            return {
                "id": row["id"],
                "envelope": envelope.model_dump(),
                "admission": admission(envelope),
            }

    def summaries(self, c, bundle_id, actor, tenant):
        rows = (
            c.execute(
                select(signed_artifacts)
                .where(
                    signed_artifacts.c.bundle_id == bundle_id,
                    signed_artifacts.c.actor == actor,
                    signed_artifacts.c.tenant == tenant,
                )
                .order_by(signed_artifacts.c.created_at.desc())
                .limit(5)
            )
            .mappings()
            .all()
        )
        result = []
        for row in rows:
            try:
                envelope = self._verify(c, row)
                status = "VERIFIED_EVIDENCE"
                blockers = admission(envelope)["blockers"]
            except (ArtifactDenied, ValueError):
                status = "UNTRUSTED"
                blockers = ["artifact_untrusted"]
            result.append(
                {
                    "id": row["id"],
                    "verification_status": status,
                    "statement_sha256": row["envelope"].get("statement_sha256", ""),
                    "key_id": row["key_id"],
                    "can_invoke": False,
                    "activation_eligible": False,
                    "blockers": blockers,
                }
            )
        return result
