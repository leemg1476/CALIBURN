"""Durable, independently approved Factory execution dispatch; no Docker import."""

import asyncio
from uuid import uuid4

from sqlalchemy import insert, select, update

from caliburn.runtime.schema import steps, tasks
from caliburn.runtime.store import LostLease
from caliburn.sandbox.contracts import Result, TestRun
from caliburn.tool_factory.checks import role
from caliburn.tool_factory.contracts import digest
from caliburn.tool_factory.execution_contracts import (
    ExecuteArgs,
    ExecutionEvidence,
    ExecutionResult,
)
from caliburn.tool_factory.oracle import require_proof
from caliburn.tool_factory.qualification import Qualification
from caliburn.tool_factory.schema import exec_jobs, exec_requests, exec_roles
from caliburn.tool_factory.service import FactoryDenied


class ExecutionQueue:
    def __init__(self, store):
        self.store = store
        self.policy = Qualification(store)

    def submit(self, task_id, token, step_id, args):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, task_id, token)
            admitted = self.policy.authorize(c, task, args.request_ref)
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
            if (
                not step
                or step["input"].get("function", {}).get("name") != "capability_execute_tests"
                or ExecuteArgs.model_validate_json(step["input"]["function"]["arguments"]) != args
            ):
                raise FactoryDenied()
            old = (
                c.execute(select(exec_jobs).where(exec_jobs.c.step_id == step_id))
                .mappings()
                .first()
            )
            if old:
                if (
                    old["request_id"] != args.request_ref
                    or old["binding_sha256"] != admitted["binding_sha256"]
                ):
                    raise FactoryDenied()
                return old["id"]
            jid = str(uuid4())
            c.execute(
                insert(exec_jobs).values(
                    id=jid,
                    task_id=task_id,
                    step_id=step_id,
                    request_id=args.request_ref,
                    tenant=task["tenant"],
                    creator_role=role(c),
                    binding_sha256=admitted["binding_sha256"],
                    state="QUEUED",
                    attempts=0,
                    created_at=self.store.now(c),
                )
            )
            self.store._event(
                c,
                task,
                "FACTORY_TEST_QUEUED",
                {
                    "job_id": jid,
                    "request_ref": args.request_ref,
                    "binding_sha256": admitted["binding_sha256"],
                },
            )
            self.store._save(c, task)
            return jid

    def poll(self, task_id, token, job_id):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, task_id, token)
            row = (
                c.execute(
                    select(exec_jobs).where(
                        exec_jobs.c.id == job_id, exec_jobs.c.task_id == task_id
                    )
                )
                .mappings()
                .first()
            )
            if not row:
                raise FactoryDenied()
            self.policy.authorize(c, task, row["request_id"])
            if row["result"] is not None:
                if digest(row["result"]) != row["result_sha256"]:
                    raise FactoryDenied()
                result = ExecutionResult.model_validate(row["result"])
                if result.ok:
                    proof = result.data
                    if (
                        proof.binding_sha256 != row["binding_sha256"]
                        or proof.request_ref != row["request_id"]
                    ):
                        raise FactoryDenied()
                return result.model_dump()
            return None

    async def invoke(self, task_id, token, step_id, args):
        jid = await asyncio.to_thread(self.submit, task_id, token, step_id, args)
        while True:
            result = await asyncio.to_thread(self.poll, task_id, token, jid)
            if result is not None:
                return result
            await asyncio.sleep(0.05)

    def claim(self, image, tools=()):
        with self.store.engine.begin() as c:
            who = (
                c.execute(
                    select(exec_roles).where(
                        exec_roles.c.db_role == role(c),
                        exec_roles.c.kind == "EXECUTOR",
                        exec_roles.c.enabled == "yes",
                    )
                )
                .mappings()
                .first()
            )
            if not who:
                raise FactoryDenied()
            self.policy.identity(c, "EXECUTOR", who["tenant"])
            now = self.store.now(c)
            row = (
                c.execute(
                    select(exec_jobs)
                    .join(tasks, tasks.c.id == exec_jobs.c.task_id)
                    .join(exec_requests, exec_requests.c.id == exec_jobs.c.request_id)
                    .where(
                        exec_jobs.c.tenant == who["tenant"],
                        exec_requests.c.binding["image_digest"].as_string() == image,
                        tasks.c.state.not_in(["PAUSED", "WAITING_APPROVAL"]),
                        (exec_jobs.c.state == "QUEUED")
                        | ((exec_jobs.c.state == "RUNNING") & (exec_jobs.c.lease_until <= now)),
                    )
                    .order_by(exec_jobs.c.created_at)
                    .with_for_update(skip_locked=True, of=exec_jobs)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not row:
                return None
            task = c.execute(select(tasks).where(tasks.c.id == row["task_id"])).mappings().one()
            try:
                job = self.policy.authorize(c, task, row["request_id"], image)
                if (
                    row["attempts"] >= min(3, task["limits"]["max_retries"] + 1)
                    or row["binding_sha256"] != job["binding_sha256"]
                    or role(c) == row["creator_role"]
                ):
                    raise FactoryDenied()
            except FactoryDenied:
                result = ExecutionResult(ok=False, error="factory_execution_denied").model_dump()
                c.execute(
                    update(exec_jobs)
                    .where(exec_jobs.c.id == row["id"])
                    .values(
                        state="DENIED",
                        result=result,
                        result_sha256=digest(result),
                        lease_token=None,
                        lease_until=None,
                    )
                )
                return None
            token = str(uuid4())
            c.execute(
                update(exec_jobs)
                .where(exec_jobs.c.id == row["id"])
                .values(
                    state="RUNNING",
                    executor_role=role(c),
                    lease_token=token,
                    lease_until=min(now + 15, task["deadline"]),
                    attempts=row["attempts"] + 1,
                )
            )
            return dict(row) | job | {"lease_token": token, "image": image}

    def _owned(self, c, job):
        row = (
            c.execute(select(exec_jobs).where(exec_jobs.c.id == job["id"]).with_for_update())
            .mappings()
            .first()
        )
        if not row:
            raise FactoryDenied()
        self.policy.identity(c, "EXECUTOR", row["tenant"])
        task = c.execute(select(tasks).where(tasks.c.id == row["task_id"])).mappings().one()
        admitted = self.policy.authorize(c, task, row["request_id"], job["image"])
        if (
            row["state"] != "RUNNING"
            or row["executor_role"] != role(c)
            or row["lease_token"] != job["lease_token"]
            or row["lease_until"] <= self.store.now(c)
            or row["binding_sha256"] != admitted["binding_sha256"]
        ):
            raise FactoryDenied()
        return row, task, admitted

    def heartbeat(self, job):
        try:
            with self.store.engine.begin() as c:
                row, task, _ = self._owned(c, job)
                c.execute(
                    update(exec_jobs)
                    .where(exec_jobs.c.id == row["id"])
                    .values(lease_until=min(self.store.now(c) + 15, task["deadline"]))
                )
            return True
        except FactoryDenied:
            return False

    def finish(self, job, result):
        try:
            return self._finish(job, result)
        except FactoryDenied as exc:
            raise LostLease() from exc

    def _finish(self, job, result):
        result = Result.model_validate(result.model_dump())
        with self.store.engine.begin() as c:
            row, _, admitted = self._owned(c, job)
            if result.ok:
                run = TestRun.model_validate(result.data)
                if run.status == "PASSED":
                    try:
                        proof = require_proof(admitted["binding"], result.isolation, current=True)
                    except ValueError as exc:
                        raise FactoryDenied() from exc
                    if proof.status != "PASSED":
                        raise FactoryDenied()
                if (
                    run.source_sha256 != admitted["binding"]["source_sha256"]
                    or run.plan_sha256 != admitted["binding"]["plan_sha256"]
                ):
                    raise FactoryDenied()
                result.data = ExecutionEvidence(
                    executor_role=role(c),
                    request_ref=row["request_id"],
                    binding_sha256=row["binding_sha256"],
                    image_digest=job["image"],
                    run=run,
                    source_executed=True,
                    production_approved=False,
                    security="INCOMPLETE",
                    license="UNREVIEWED",
                ).model_dump()
            projected = result.model_dump(exclude={"candidate_ref"})
            if not result.ok:
                projected["data"] = None
            payload = ExecutionResult.model_validate(projected).model_dump()
            c.execute(
                update(exec_jobs)
                .where(exec_jobs.c.id == row["id"])
                .values(
                    state="COMPLETED",
                    result=payload,
                    result_sha256=digest(payload),
                    lease_token=None,
                    lease_until=None,
                )
            )
