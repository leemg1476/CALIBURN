"""Independent static-check queue and append-only evidence; no candidate execution."""

import asyncio
import re
from uuid import uuid4

from sqlalchemy import insert, select, text, update

from caliburn.runtime.schema import steps, tasks
from caliburn.runtime.store import NotFound
from caliburn.tool_factory.contracts import (
    CHECKER_DIGEST,
    FACTORY_DIGEST,
    CheckArgs,
    CheckResult,
    StaticReport,
    digest,
)
from caliburn.tool_factory.schema import bundles, check_jobs, check_reports, verifiers
from caliburn.tool_factory.service import Factory, FactoryDenied


def role(c):
    return (
        c.scalar(text("SELECT current_user"))
        if c.dialect.name == "postgresql"
        else "sqlite-no-verifier"
    )


def mutable_runtime(c, name):
    return c.scalar(
        text(
            "SELECT has_table_privilege(:name,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE') OR has_table_privilege(:name,format('%I.factory_bundles',current_schema()),'INSERT,UPDATE,DELETE')"
        ),
        {"name": name},
    )


class CheckQueue:
    def __init__(self, store):
        self.store = store

    def submit(self, task_id, token, step_id, args: CheckArgs):
        with self.store.engine.begin() as c:
            task = Factory(self.store)._authorized(c, task_id, token, "capability_check")
            step = (
                c.execute(
                    select(steps).where(
                        steps.c.id == step_id,
                        steps.c.task_id == task_id,
                        steps.c.kind == "TOOL",
                        steps.c.status == "STARTED",
                    )
                )
                .mappings()
                .first()
            )
            if not step or step["input"].get("function", {}).get("name") != "capability_check":
                raise FactoryDenied()
            try:
                recorded = CheckArgs.model_validate_json(step["input"]["function"]["arguments"])
            except (ValueError, KeyError) as exc:
                raise FactoryDenied() from exc
            if args != recorded:
                raise FactoryDenied()
            bundle = (
                c.execute(
                    select(bundles).where(
                        bundles.c.id == args.bundle_ref,
                        bundles.c.actor == task["actor"],
                        bundles.c.tenant == task["tenant"],
                    )
                )
                .mappings()
                .first()
            )
            if not bundle or digest(bundle["payload"]) != bundle["sha256"]:
                raise FactoryDenied()
            existing = (
                c.execute(select(check_jobs).where(check_jobs.c.step_id == step_id))
                .mappings()
                .first()
            )
            if existing:
                if (
                    existing["bundle_id"] != args.bundle_ref
                    or existing["checker_sha256"] != CHECKER_DIGEST
                ):
                    raise FactoryDenied()
                return existing["id"]
            job_id = str(uuid4())
            c.execute(
                insert(check_jobs).values(
                    id=job_id,
                    task_id=task_id,
                    step_id=step_id,
                    bundle_id=bundle["id"],
                    actor=task["actor"],
                    tenant=task["tenant"],
                    creator_role=role(c),
                    bundle_sha256=bundle["sha256"],
                    checker_sha256=CHECKER_DIGEST,
                    state="QUEUED",
                    created_at=self.store.now(c),
                    deadline=task["deadline"],
                    attempts=0,
                )
            )
            self.store._event(
                c,
                task,
                "CAPABILITY_CHECK_REQUESTED",
                {"job_id": job_id, "bundle_id": bundle["id"], "checker_sha256": CHECKER_DIGEST},
            )
            self.store._save(c, task)
            return job_id

    def result(self, task_id, token, job_id):
        with self.store.engine.begin() as c:
            task = Factory(self.store)._authorized(c, task_id, token, "capability_check")
            job = (
                c.execute(
                    select(check_jobs).where(
                        check_jobs.c.id == job_id, check_jobs.c.task_id == task["id"]
                    )
                )
                .mappings()
                .first()
            )
            if (
                not job
                or job["checker_sha256"] != CHECKER_DIGEST
                or job["state"] in {"FAILED", "CANCELLED"}
            ):
                raise FactoryDenied()
            report = (
                c.execute(select(check_reports).where(check_reports.c.job_id == job_id))
                .mappings()
                .first()
            )
            if not report or job["state"] != "FINISHED":
                return None
            body = StaticReport.model_validate(report["body"])
            if (
                digest(body.model_dump()) != report["body_sha256"]
                or body.bundle_sha256 != job["bundle_sha256"]
                or body.checker_sha256 != job["checker_sha256"]
            ):
                raise FactoryDenied()
            return CheckResult(
                report_ref=report["id"], report_sha256=report["body_sha256"], report=body
            ).model_dump()

    async def invoke(self, task_id, token, step_id, args):
        job_id = await asyncio.to_thread(self.submit, task_id, token, step_id, args)
        while True:
            result = await asyncio.to_thread(self.result, task_id, token, job_id)
            if result is not None:
                return result
            await asyncio.sleep(0.05)

    def read(self, report_id, actor="development-service", tenant="development"):
        with self.store.engine.connect() as c:
            row = (
                c.execute(
                    select(
                        check_reports,
                        check_jobs.c.bundle_id,
                        check_jobs.c.bundle_sha256,
                        check_jobs.c.checker_sha256,
                    )
                    .join(check_jobs, check_jobs.c.id == check_reports.c.job_id)
                    .where(
                        check_reports.c.id == report_id,
                        check_jobs.c.actor == actor,
                        check_jobs.c.tenant == tenant,
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise NotFound()
            body = StaticReport.model_validate(row["body"])
            if (
                digest(body.model_dump()) != row["body_sha256"]
                or body.bundle_sha256 != row["bundle_sha256"]
                or body.checker_sha256 != row["checker_sha256"]
            ):
                raise FactoryDenied()
            return {
                "id": row["id"],
                "bundle_id": row["bundle_id"],
                "job_id": row["job_id"],
                "verifier_role": row["verifier_role"],
                "created_at": row["created_at"],
                "sha256": row["body_sha256"],
                "report": body.model_dump(),
            }


class VerifierAuthority:
    def __init__(self, store):
        self.store = store

    def _owner(self, c):
        if c.dialect.name != "postgresql" or not c.scalar(
            text(
                "SELECT r.rolsuper OR n.nspowner=r.oid FROM pg_roles r, pg_namespace n WHERE r.rolname=current_user AND n.nspname=current_schema()"
            )
        ):
            raise FactoryDenied()

    def configure(self, db_role, principal, tenant="development"):
        if (
            not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", db_role)
            or not 1 <= len(principal) <= 80
            or not 1 <= len(tenant) <= 100
        ):
            raise ValueError("Invalid verifier identity")
        with self.store.engine.begin() as c:
            self._owner(c)
            if db_role == role(c) or not c.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:name)"), {"name": db_role}
            ):
                raise FactoryDenied()
            if mutable_runtime(c, db_role):
                raise FactoryDenied()
            existing = (
                c.execute(select(verifiers).where(verifiers.c.db_role == db_role))
                .mappings()
                .first()
            )
            if existing and (
                existing["principal"] != principal
                or existing["tenant"] != tenant
                or existing["enabled"] != "yes"
            ):
                raise FactoryDenied()
            if not existing:
                c.execute(
                    insert(verifiers).values(
                        db_role=db_role, principal=principal, tenant=tenant, enabled="yes"
                    )
                )
            schema = c.scalar(text("SELECT current_schema()")).replace('"', '""')
            c.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{db_role}"'))
            for table in (
                "factory_verifiers",
                "factory_bundles",
                "factory_check_jobs",
                "factory_check_reports",
                "runtime_tasks",
            ):
                c.execute(text(f'GRANT SELECT ON "{schema}".{table} TO "{db_role}"'))
            c.execute(text(f'GRANT INSERT ON "{schema}".factory_check_reports TO "{db_role}"'))
            c.execute(
                text(
                    f'GRANT UPDATE (state,attempts,lease_token,lease_until,error) ON "{schema}".factory_check_jobs TO "{db_role}"'
                )
            )
            # SELECT FOR UPDATE on task rows requires an UPDATE column privilege.
            # Never grant task mutation to the verifier; queue locks use job rows only.

    def disable(self, db_role):
        with self.store.engine.begin() as c:
            self._owner(c)
            c.execute(update(verifiers).where(verifiers.c.db_role == db_role).values(enabled="no"))

    def identity(self, c, tenant=None):
        if c.dialect.name != "postgresql":
            raise FactoryDenied()
        row = (
            c.execute(
                select(verifiers).where(
                    verifiers.c.db_role == role(c), verifiers.c.enabled == "yes"
                )
            )
            .mappings()
            .first()
        )
        if (
            not row
            or (tenant is not None and row["tenant"] != tenant)
            or mutable_runtime(c, role(c))
        ):
            raise FactoryDenied()
        return row

    def claim(self, lease_seconds=15):
        if not 0.1 <= lease_seconds <= 60:
            raise ValueError("Invalid verifier lease")
        with self.store.engine.begin() as c:
            identity = self.identity(c)
            now = self.store.now(c)
            job = (
                c.execute(
                    select(check_jobs)
                    .join(tasks, tasks.c.id == check_jobs.c.task_id)
                    .where(
                        check_jobs.c.tenant == identity["tenant"],
                        tasks.c.state.not_in(["PAUSED", "WAITING_APPROVAL"]),
                        (check_jobs.c.state == "QUEUED")
                        | ((check_jobs.c.state == "RUNNING") & (check_jobs.c.lease_until <= now)),
                    )
                    .order_by(check_jobs.c.created_at)
                    .with_for_update(skip_locked=True, of=check_jobs)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not job:
                return None
            task = c.execute(select(tasks).where(tasks.c.id == job["task_id"])).mappings().one()
            bundle = (
                c.execute(select(bundles).where(bundles.c.id == job["bundle_id"])).mappings().one()
            )
            if job["creator_role"] == role(c) or bundle["creator_role"] == role(c):
                raise FactoryDenied()
            if task["state"] in {"PAUSED", "WAITING_APPROVAL"}:
                return None
            failure = (
                "task_ended"
                if task["state"] != "RUNNING" or task["deadline"] <= now
                else "retry_limit"
                if job["attempts"] >= 3
                else "checker_revision_changed"
                if job["checker_sha256"] != CHECKER_DIGEST
                else None
            )
            if failure:
                c.execute(
                    update(check_jobs)
                    .where(check_jobs.c.id == job["id"])
                    .values(
                        state="CANCELLED" if failure == "task_ended" else "FAILED",
                        error=failure,
                        lease_token=None,
                        lease_until=None,
                    )
                )
                return None
            if (
                bundle["actor"] != job["actor"]
                or bundle["tenant"] != job["tenant"]
                or digest(bundle["payload"]) != job["bundle_sha256"]
            ):
                raise FactoryDenied()
            token = str(uuid4())
            c.execute(
                update(check_jobs)
                .where(check_jobs.c.id == job["id"])
                .values(
                    state="RUNNING",
                    attempts=job["attempts"] + 1,
                    lease_token=token,
                    lease_until=min(now + lease_seconds, job["deadline"]),
                )
            )
            return dict(job) | {"lease_token": token, "payload": bundle["payload"]}

    def _owned(self, c, job_id, token):
        job = (
            c.execute(select(check_jobs).where(check_jobs.c.id == job_id).with_for_update())
            .mappings()
            .first()
        )
        if not job:
            raise FactoryDenied()
        self.identity(c, job["tenant"])
        task = c.execute(select(tasks).where(tasks.c.id == job["task_id"])).mappings().one()
        now = self.store.now(c)
        if (
            job["state"] != "RUNNING"
            or job["lease_token"] != token
            or job["lease_until"] <= now
            or task["state"] != "RUNNING"
            or task["deadline"] <= now
            or job["checker_sha256"] != CHECKER_DIGEST
            or task["policy"].get("factory_digest") != FACTORY_DIGEST
            or "capability_check" not in task["policy"]["tools"]
        ):
            raise FactoryDenied()
        return job

    def finish(self, job_id, token, body):
        body = StaticReport.model_validate(body).model_dump()
        with self.store.engine.begin() as c:
            job = self._owned(c, job_id, token)
            if (
                body["bundle_sha256"] != job["bundle_sha256"]
                or body["checker_sha256"] != job["checker_sha256"]
            ):
                raise FactoryDenied()
            report_id = str(uuid4())
            c.execute(
                insert(check_reports).values(
                    id=report_id,
                    job_id=job_id,
                    lease_token=token,
                    verifier_role=role(c),
                    body=body,
                    body_sha256=digest(body),
                    created_at=self.store.now(c),
                )
            )
            c.execute(
                update(check_jobs)
                .where(check_jobs.c.id == job_id)
                .values(state="FINISHED", lease_token=None, lease_until=None)
            )
            return report_id
