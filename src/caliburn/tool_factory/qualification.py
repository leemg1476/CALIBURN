"""Separate Factory sandbox execution review. No source execution or Docker here."""

import json
import re
from uuid import uuid4

from sqlalchemy import insert, select, text, update

from caliburn.runtime.schema import tasks
from caliburn.runtime.store import NotFound
from caliburn.sandbox.contracts import Bundle
from caliburn.tool_factory.checks import VerifierAuthority, mutable_runtime, role
from caliburn.tool_factory.contracts import (
    CHECKER_DIGEST,
    FACTORY_DIGEST,
    CapabilityBundle,
    StaticReport,
    digest,
    matches,
)
from caliburn.tool_factory.execution_contracts import EXEC_DIGEST, ExecutionAdmission
from caliburn.tool_factory.oracle import PLAN_FILE, OraclePlan, plan_digest, read_plan
from caliburn.tool_factory.schema import (
    bundles,
    check_jobs,
    check_reports,
    exec_decisions,
    exec_jobs,
    exec_plans,
    exec_requests,
    exec_revocations,
    exec_roles,
    verifiers,
)
from caliburn.tool_factory.service import FactoryDenied


def contract_plan(payload, independent):
    """Build reviewable test text only; it runs exclusively in the approved container."""
    bundle = CapabilityBundle.model_validate(payload)
    path, _, symbol = bundle.manifest.entrypoint.partition(":")
    probe = """import importlib.util
import json
import unittest
from pathlib import Path

class ContractFixtureTest(unittest.TestCase):
    def strict_equal(self, actual, expected):
        self.assertIs(type(actual), type(expected))
        if isinstance(expected, dict):
            self.assertEqual(set(actual), set(expected))
            for key in expected: self.strict_equal(actual[key], expected[key])
        elif isinstance(expected, list):
            self.assertEqual(len(actual), len(expected))
            for a, b in zip(actual, expected): self.strict_equal(a, b)
        else: self.assertEqual(actual, expected)

    def test_declared_fixtures(self):
        path = Path('/work/src') / SOURCE_PATH
        spec = importlib.util.spec_from_file_location('_factory_subject', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        fn = getattr(module, SYMBOL)
        for fixture in json.loads(FIXTURES):
            with self.subTest(name=fixture['name']):
                self.strict_equal(fn(**fixture['input']), fixture['expected'])
"""
    header = f"SOURCE_PATH = {path!r}\nSYMBOL = {symbol!r}\nFIXTURES = {json.dumps(payload['fixtures'], ensure_ascii=True)!r}\n"
    all_files = {"test_caliburn_contract.py": header + probe}
    for group in (bundle.tests, independent.files):
        if {name.casefold() for name in group} & {name.casefold() for name in all_files}:
            raise FactoryDenied()
        all_files.update(group)
    return Bundle(files=all_files)


class Qualification:
    def __init__(self, store):
        self.store = store

    def configure(self, db_role, principal, kind, tenant="development"):
        if (
            kind not in {"REVIEWER", "EXECUTOR"}
            or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", db_role)
            or not 1 <= len(principal) <= 80
            or not 1 <= len(tenant) <= 100
        ):
            raise ValueError("Invalid Factory authority")
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            if not c.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:name)"), {"name": db_role}
            ) or mutable_runtime(c, db_role):
                raise FactoryDenied()
            old = (
                c.execute(select(exec_roles).where(exec_roles.c.db_role == db_role))
                .mappings()
                .first()
            )
            if old and any(
                old[key] != value
                for key, value in {
                    "principal": principal,
                    "kind": kind,
                    "tenant": tenant,
                    "enabled": "yes",
                }.items()
            ):
                raise FactoryDenied()
            if not old:
                c.execute(
                    insert(exec_roles).values(
                        db_role=db_role,
                        principal=principal,
                        kind=kind,
                        tenant=tenant,
                        enabled="yes",
                    )
                )
            schema = c.scalar(text("SELECT current_schema()")).replace('"', '""')
            c.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{db_role}"'))
            for table in (
                "factory_exec_roles",
                "factory_exec_plans",
                "factory_exec_requests",
                "factory_exec_decisions",
                "factory_exec_revocations",
                "factory_exec_jobs",
                "factory_bundles",
                "factory_check_jobs",
                "factory_check_reports",
                "factory_verifiers",
                "runtime_tasks",
            ):
                c.execute(text(f'GRANT SELECT ON "{schema}".{table} TO "{db_role}"'))
            if kind == "REVIEWER":
                c.execute(
                    text(
                        f'GRANT INSERT ON "{schema}".factory_exec_decisions,"{schema}".factory_exec_revocations TO "{db_role}"'
                    )
                )
            else:
                c.execute(
                    text(
                        f'GRANT UPDATE (state,attempts,lease_token,lease_until,result,result_sha256,executor_role) ON "{schema}".factory_exec_jobs TO "{db_role}"'
                    )
                )

    def identity(self, c, kind, tenant):
        if c.dialect.name != "postgresql" or mutable_runtime(c, role(c)):
            raise FactoryDenied()
        row = (
            c.execute(
                select(exec_roles).where(
                    exec_roles.c.db_role == role(c),
                    exec_roles.c.kind == kind,
                    exec_roles.c.tenant == tenant,
                    exec_roles.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise FactoryDenied()
        return row

    def disable(self, db_role):
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            c.execute(
                update(exec_roles).where(exec_roles.c.db_role == db_role).values(enabled="no")
            )

    def _artifacts(self, c, bundle_id, report_id):
        bundle = c.execute(select(bundles).where(bundles.c.id == bundle_id)).mappings().first()
        report = (
            c.execute(select(check_reports).where(check_reports.c.id == report_id))
            .mappings()
            .first()
        )
        if not bundle or not report:
            raise FactoryDenied()
        body = StaticReport.model_validate(report["body"])
        check = (
            c.execute(select(check_jobs).where(check_jobs.c.id == report["job_id"]))
            .mappings()
            .one()
        )
        verifier = (
            c.execute(
                select(verifiers).where(
                    verifiers.c.db_role == report["verifier_role"],
                    verifiers.c.tenant == bundle["tenant"],
                    verifiers.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        payload = CapabilityBundle.model_validate(bundle["payload"])
        if (
            not verifier
            or body.classification != "REVIEW_REQUIRED"
            or body.checker_sha256 != CHECKER_DIGEST
            or check["bundle_id"] != bundle_id
            or check["state"] != "FINISHED"
            or check["actor"] != bundle["actor"]
            or check["tenant"] != bundle["tenant"]
            or digest(body.model_dump()) != report["body_sha256"]
            or digest(bundle["payload"]) != bundle["sha256"]
            or body.bundle_sha256 != bundle["sha256"]
            or payload.manifest.kind != "tool"
            or payload.dependency_lock
            or payload.manifest.permissions
        ):
            raise FactoryDenied()
        return bundle, report

    def register_plan(
        self,
        bundle_id,
        report_id,
        independent: Bundle,
        image_digest,
        ttl_seconds=3600,
        *,
        oracle_cases=None,
    ):
        if (
            not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest)
            or type(ttl_seconds) is not int
            or not 1 <= ttl_seconds <= 86400
        ):
            raise ValueError("Invalid image/plan TTL")
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            bundle, _ = self._artifacts(c, bundle_id, report_id)
            plan = contract_plan(bundle["payload"], independent)
            if PLAN_FILE in plan.files:
                raise FactoryDenied()
            oracle = OraclePlan(
                case_source="operator" if oracle_cases is not None else "bundle_declared",
                entrypoint=bundle["payload"]["manifest"]["entrypoint"],
                cases=oracle_cases if oracle_cases is not None else bundle["payload"]["fixtures"],
            )
            manifest = bundle["payload"]["manifest"]
            if any(
                not matches(manifest["input_schema"], case.input)
                or not matches(manifest["output_schema"], case.expected)
                for case in oracle.cases
            ):
                raise FactoryDenied()
            plan = Bundle(files=plan.files | {PLAN_FILE: oracle.model_dump_json()})
            pid = str(uuid4())
            now = self.store.now(c)
            c.execute(
                insert(exec_plans).values(
                    id=pid,
                    bundle_id=bundle_id,
                    report_id=report_id,
                    actor=bundle["actor"],
                    tenant=bundle["tenant"],
                    owner_role=role(c),
                    files=plan.files,
                    sha256=plan.digest(),
                    image_digest=image_digest,
                    created_at=now,
                    expires_at=now + ttl_seconds,
                )
            )
            return pid

    def binding(self, c, task, plan_id):
        if (
            c.dialect.name != "postgresql"
            or task["policy"].get("exec_digest") != EXEC_DIGEST
            or task["policy"].get("factory_digest") != FACTORY_DIGEST
            or not {"capability_request_execution", "capability_execute_tests"}
            <= set(task["policy"]["tools"])
        ):
            raise FactoryDenied()
        plan = (
            c.execute(
                select(exec_plans).where(
                    exec_plans.c.id == plan_id,
                    exec_plans.c.actor == task["actor"],
                    exec_plans.c.tenant == task["tenant"],
                )
            )
            .mappings()
            .first()
        )
        if not plan or plan["expires_at"] <= self.store.now(c):
            raise FactoryDenied()
        bundle, report = self._artifacts(c, plan["bundle_id"], plan["report_id"])
        files = Bundle(files=plan["files"])
        source = Bundle(files=bundle["payload"]["sources"])
        if files.digest() != plan["sha256"]:
            raise FactoryDenied()
        oracle = read_plan(files.files)
        if oracle.entrypoint != bundle["payload"]["manifest"]["entrypoint"]:
            raise FactoryDenied()
        binding = {
            "version": "factory-execution-v2",
            "oracle_sha256": plan_digest(oracle),
            "oracle_cases": len(oracle.cases),
            "scope": "factory_sandbox_test_only",
            "task_id": task["id"],
            "actor": task["actor"],
            "tenant": task["tenant"],
            "bundle_ref": bundle["id"],
            "bundle_sha256": bundle["sha256"],
            "source_sha256": source.digest(),
            "report_ref": report["id"],
            "report_sha256": report["body_sha256"],
            "checker_sha256": CHECKER_DIGEST,
            "plan_ref": plan_id,
            "plan_sha256": plan["sha256"],
            "child_plan_sha256": Bundle(
                files={k: v for k, v in files.files.items() if k != PLAN_FILE}
            ).digest(),
            "image_digest": plan["image_digest"],
            "implementation_sha256": EXEC_DIGEST,
            "limits": task["limits"],
        }
        return binding, bundle, report, plan

    def state(self, c, req, task):
        binding, _, _, _ = self.binding(c, task, req["plan_id"])
        if binding != req["binding"] or digest(binding) != req["sha256"]:
            raise FactoryDenied()
        if min(task["deadline"], req["expires_at"]) <= self.store.now(c):
            return "EXPIRED"
        if c.execute(
            select(exec_revocations).where(exec_revocations.c.request_id == req["id"])
        ).first():
            return "REVOKED"
        decision = (
            c.execute(select(exec_decisions).where(exec_decisions.c.request_id == req["id"]))
            .mappings()
            .first()
        )
        if not decision:
            return "PENDING"
        row = (
            c.execute(
                select(exec_roles).where(
                    exec_roles.c.db_role == decision["reviewer_role"],
                    exec_roles.c.kind == "REVIEWER",
                    exec_roles.c.tenant == task["tenant"],
                    exec_roles.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        if not row or mutable_runtime(c, row["db_role"]):
            return "REVOKED"
        if decision["binding_sha256"] != req["sha256"] or decision["expires_at"] <= self.store.now(
            c
        ):
            return "EXPIRED"
        return "APPROVED" if decision["decision"] == "APPROVE" else "REJECTED"

    def ensure(self, task_id, token, args, call_key):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, task_id, token)
            if task["tool_calls"] >= task["limits"]["max_tool_calls"]:
                raise FactoryDenied()
            binding, _, _, plan = self.binding(c, task, args.plan_ref)
            req = (
                c.execute(
                    select(exec_requests).where(
                        exec_requests.c.task_id == task_id, exec_requests.c.call_key == call_key
                    )
                )
                .mappings()
                .first()
            )
            if not req:
                req = {
                    "id": str(uuid4()),
                    "task_id": task_id,
                    "plan_id": args.plan_ref,
                    "call_key": call_key,
                    "creator_role": role(c),
                    "binding": binding,
                    "sha256": digest(binding),
                    "created_at": self.store.now(c),
                    "expires_at": min(task["deadline"], plan["expires_at"]),
                }
                c.execute(insert(exec_requests).values(**req))
                self.store._event(
                    c,
                    task,
                    "FACTORY_EXECUTION_REVIEW_REQUESTED",
                    {"request_ref": req["id"], "binding_sha256": req["sha256"]},
                )
            if (
                req["plan_id"] != args.plan_ref
                or req["binding"] != binding
                or req["sha256"] != digest(binding)
            ):
                raise FactoryDenied()
            state = self.state(c, req, task)
            if state == "APPROVED":
                return ExecutionAdmission(
                    request_ref=req["id"],
                    binding_sha256=req["sha256"],
                    status="APPROVED_FOR_FACTORY_SANDBOX_TEST",
                    scope="factory_sandbox_test_only",
                    source_executed=False,
                    production_approved=False,
                ).model_dump()
            if state != "PENDING":
                raise FactoryDenied()
            self.store._end(c, task, "WAITING_APPROVAL")
            return None

    def _reviewer(self, c, req, task):
        identity = self.identity(c, "REVIEWER", task["tenant"])
        _, bundle, report, plan = self.binding(c, task, req["plan_id"])
        if (
            role(c)
            in {
                req["creator_role"],
                bundle["creator_role"],
                report["verifier_role"],
                plan["owner_role"],
            }
            or identity["principal"] == task["actor"]
        ):
            raise FactoryDenied()

    def decide(self, request_id, expected_sha, decision, ttl_seconds=600):
        if (
            decision not in {"APPROVE", "REJECT"}
            or type(ttl_seconds) is not int
            or not 1 <= ttl_seconds <= 3600
        ):
            raise ValueError("Invalid decision")
        with self.store.engine.begin() as c:
            req = (
                c.execute(select(exec_requests).where(exec_requests.c.id == request_id))
                .mappings()
                .first()
            )
            if not req:
                raise NotFound()
            task = c.execute(select(tasks).where(tasks.c.id == req["task_id"])).mappings().one()
            self._reviewer(c, req, task)
            if (
                task["state"] != "WAITING_APPROVAL"
                or self.state(c, req, task) != "PENDING"
                or req["sha256"] != expected_sha
            ):
                raise FactoryDenied()
            c.execute(
                insert(exec_decisions).values(
                    id=str(uuid4()),
                    request_id=request_id,
                    reviewer_role=role(c),
                    decision=decision,
                    binding_sha256=expected_sha,
                    created_at=self.store.now(c),
                    expires_at=min(req["expires_at"], self.store.now(c) + ttl_seconds),
                )
            )

    def revoke(self, request_id):
        with self.store.engine.begin() as c:
            req = (
                c.execute(select(exec_requests).where(exec_requests.c.id == request_id))
                .mappings()
                .first()
            )
            if not req:
                raise NotFound()
            task = c.execute(select(tasks).where(tasks.c.id == req["task_id"])).mappings().one()
            self._reviewer(c, req, task)
            if not c.execute(
                select(exec_decisions).where(exec_decisions.c.request_id == request_id)
            ).first():
                raise FactoryDenied()
            c.execute(
                insert(exec_revocations).values(
                    request_id=request_id, reviewer_role=role(c), created_at=self.store.now(c)
                )
            )

    def wake(self, c, task):
        req = (
            c.execute(
                select(exec_requests)
                .where(exec_requests.c.task_id == task["id"])
                .order_by(exec_requests.c.created_at.desc(), exec_requests.c.id.desc())
                .limit(1)
            )
            .mappings()
            .first()
        )
        if not req:
            return
        try:
            state = self.state(c, req, task)
        except (FactoryDenied, ValueError):
            state = "INVALID"
        if state == "PENDING":
            return
        if state == "APPROVED":
            task["state"] = "QUEUED"
            self.store._event(
                c, task, "FACTORY_EXECUTION_REVIEW_APPROVED", {"request_ref": req["id"]}
            )
            self.store._save(c, task)
        else:
            self.store._end(c, task, "FAILED", "factory_review_" + state.lower())

    @staticmethod
    def wakeable(now):
        latest = (
            select(exec_requests.c.id)
            .where(exec_requests.c.task_id == tasks.c.id)
            .order_by(exec_requests.c.created_at.desc(), exec_requests.c.id.desc())
            .limit(1)
            .correlate(tasks)
            .scalar_subquery()
        )
        decided = (
            select(exec_decisions.c.id)
            .where(exec_decisions.c.request_id == exec_requests.c.id)
            .exists()
        )
        revoked = (
            select(exec_revocations.c.request_id)
            .where(exec_revocations.c.request_id == exec_requests.c.id)
            .exists()
        )
        return (
            select(exec_requests.c.id)
            .where(
                exec_requests.c.id == latest,
                (exec_requests.c.expires_at <= now) | decided | revoked,
            )
            .correlate(tasks)
            .exists()
        )

    def authorize(self, c, task, request_id, image=None):
        req = (
            c.execute(
                select(exec_requests).where(
                    exec_requests.c.id == request_id, exec_requests.c.task_id == task["id"]
                )
            )
            .mappings()
            .first()
        )
        if not req or self.state(c, req, task) != "APPROVED":
            raise FactoryDenied()
        binding, bundle, _, plan = self.binding(c, task, req["plan_id"])
        if (
            task["state"] != "RUNNING"
            or task["lease_until"] <= self.store.now(c)
            or task["deadline"] <= self.store.now(c)
            or (image is not None and image != plan["image_digest"])
        ):
            raise FactoryDenied()
        return {
            "request_ref": request_id,
            "binding_sha256": req["sha256"],
            "binding": binding,
            "source_files": bundle["payload"]["sources"],
            "plan_files": plan["files"],
        }

    def inspect(self, request_id):
        with self.store.engine.begin() as c:
            req = (
                c.execute(select(exec_requests).where(exec_requests.c.id == request_id))
                .mappings()
                .first()
            )
            if not req:
                raise NotFound()
            table = tasks
            task = c.execute(select(table).where(table.c.id == req["task_id"])).mappings().one()
            self._reviewer(c, req, task)
            binding, bundle, report, plan = self.binding(c, task, req["plan_id"])
            return {
                "request_ref": request_id,
                "binding": binding,
                "binding_sha256": req["sha256"],
                "bundle": bundle["payload"],
                "static_report": report["body"],
                "test_plan_files": plan["files"],
                "status": self.state(c, req, task),
                "dispatch_attempted": c.execute(
                    select(exec_jobs.c.id).where(
                        exec_jobs.c.request_id == request_id, exec_jobs.c.attempts > 0
                    )
                ).first()
                is not None,
            }

    def views(self, task_id, actor="development-service", tenant="development"):
        with self.store.engine.begin() as c:
            task = (
                c.execute(
                    select(tasks).where(
                        tasks.c.id == task_id, tasks.c.actor == actor, tasks.c.tenant == tenant
                    )
                )
                .mappings()
                .first()
            )
            if not task:
                raise NotFound()
            rows = (
                c.execute(
                    select(exec_requests)
                    .where(exec_requests.c.task_id == task_id)
                    .order_by(exec_requests.c.created_at.desc())
                    .limit(20)
                )
                .mappings()
                .all()
            )
            result = []
            for req in rows:
                try:
                    state = self.state(c, req, task)
                except (FactoryDenied, ValueError):
                    state = "INVALID"
                dispatched = (
                    c.execute(
                        select(exec_jobs.c.id).where(
                            exec_jobs.c.request_id == req["id"], exec_jobs.c.attempts > 0
                        )
                    ).first()
                    is not None
                )
                result.append(
                    {
                        "id": req["id"],
                        "binding_sha256": req["sha256"],
                        "binding": req["binding"],
                        "status": state,
                        "expires_at": req["expires_at"],
                        "dispatch_attempted": dispatched,
                        "production_approved": False,
                    }
                )
            return result
