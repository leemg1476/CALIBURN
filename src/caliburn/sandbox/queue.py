"""Workspace grants and dispatch persistence. No Docker or host execution imports."""

import asyncio
import re
from uuid import uuid4

from sqlalchemy import insert, select, update

from caliburn.policy.review import ReviewDenied, ReviewPolicy, candidate_source, record_candidate
from caliburn.policy.schema import candidates
from caliburn.runtime.schema import steps, tasks
from caliburn.runtime.store import Conflict, LostLease, NotFound
from caliburn.sandbox.contracts import PERMISSIONS, Bundle, Operation, Result, validate_result
from caliburn.sandbox.schema import jobs, workspaces


class WorkspaceDenied(Exception):
    pass


class WorkspaceQueue:
    def __init__(self, store):
        self.store = store

    def register(
        self,
        bundle: Bundle,
        *,
        actor="development-service",
        tenant="development",
        propose_patch=False,
        provenance=None,
        ttl_seconds=3600,
        request_review=False,
        execute_reviewed_tests=False,
        git_image_digest=None,
    ):
        # Operator-only Python/CLI entry point, never exposed as a model tool or API route.
        wid = str(uuid4())
        if any(
            type(flag) is not bool
            for flag in (propose_patch, request_review, execute_reviewed_tests)
        ):
            raise ValueError("Workspace permissions require explicit booleans")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError("Workspace grant TTL must be 1..86400 seconds")
        if execute_reviewed_tests and not (propose_patch and request_review):
            raise ValueError("Execution requires separate patch/review grants")
        if git_image_digest is not None and not re.fullmatch(
            r"sha256:[a-f0-9]{64}", git_image_digest
        ):
            raise ValueError("Immutable Git image required")
        with self.store.engine.begin() as c:
            c.execute(
                insert(workspaces).values(
                    id=wid,
                    actor=actor,
                    tenant=tenant,
                    digest=bundle.digest(),
                    files=bundle.files,
                    permissions=(["read", "propose_patch"] if propose_patch else ["read"])
                    + (["request_review"] if request_review else [])
                    + (["execute_reviewed_tests"] if execute_reviewed_tests else [])
                    + (["git_inspect"] if git_image_digest else []),
                    status="ACTIVE",
                    created_at=self.store.now(c),
                    expires_at=self.store.now(c) + ttl_seconds,
                    provenance={
                        **(provenance or {}),
                        **({"git_image_digest": git_image_digest} if git_image_digest else {}),
                    },
                )
            )
        return wid

    def authorization(self, c, task, operation, image=None):
        if operation["tool"] == "repo_git_status":
            workspace = self.workspace(c, task["workspace_ref"], task)
            pinned = workspace["provenance"].get("git_image_digest")
            if (
                not pinned
                or task["policy"].get("git_image_digest") != pinned
                or (image is not None and image != pinned)
            ):
                raise WorkspaceDenied()
            files = workspace["files"]
            candidate_id = operation["arguments"].get("candidate_ref")
            if candidate_id:
                row = (
                    c.execute(
                        select(candidates).where(
                            candidates.c.id == candidate_id,
                            candidates.c.task_id == task["id"],
                            candidates.c.workspace_id == workspace["id"],
                            candidates.c.actor == task["actor"],
                            candidates.c.tenant == task["tenant"],
                        )
                    )
                    .mappings()
                    .first()
                )
                if not row or row["base_digest"] != workspace["digest"]:
                    raise WorkspaceDenied()
                try:
                    candidate_source(c, task, workspace, row["parent_id"])
                except ReviewDenied as exc:
                    raise WorkspaceDenied() from exc
                files = Bundle(files=row["files"]).files
                if Bundle(files=files).digest() != row["artifact_digest"]:
                    raise WorkspaceDenied()
            return {
                "git_base": workspace["files"],
                "git_candidate": files,
                "git_baseline_sha256": workspace["digest"],
                "git_candidate_sha256": Bundle(files=files).digest(),
            }
        if operation["tool"] == "repo_patch":
            workspace = self.workspace(c, task["workspace_ref"], task)
            try:
                files = candidate_source(
                    c, task, workspace, operation["arguments"].get("parent_candidate_ref")
                )
            except ReviewDenied as exc:
                raise WorkspaceDenied() from exc
            return {"files": files, "digest": Bundle(files=files).digest()}
        if operation["tool"] != "repo_test":
            return {}
        try:
            return ReviewPolicy(self.store).authorize_test(
                c, task, operation["arguments"]["request_ref"], image
            )
        except ReviewDenied as exc:
            raise WorkspaceDenied() from exc

    def revoke(self, wid, *, actor="development-service", tenant="development"):
        with self.store.engine.begin() as c:
            result = c.execute(
                update(workspaces)
                .where(
                    workspaces.c.id == wid,
                    workspaces.c.actor == actor,
                    workspaces.c.tenant == tenant,
                )
                .values(status="REVOKED")
            )
            if result.rowcount != 1:
                raise NotFound()

    def workspace(self, c, wid, task):
        row = (
            c.execute(
                select(workspaces).where(
                    workspaces.c.id == wid,
                    workspaces.c.actor == task["actor"],
                    workspaces.c.tenant == task["tenant"],
                    workspaces.c.status == "ACTIVE",
                    workspaces.c.expires_at > self.store.now(c),
                )
            )
            .mappings()
            .first()
        )
        if row is None:
            raise WorkspaceDenied()
        bundle = Bundle(files=row["files"])
        if (
            row["digest"] != bundle.digest()
            or task.get("workspace_ref") != wid
            or task["policy"].get("workspace_digest") != row["digest"]
        ):
            raise WorkspaceDenied()
        return dict(row)

    def request(self, task_id, token, step_id, operation: Operation):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, task_id, token)
            workspace = self.workspace(c, task["workspace_ref"], task)
            if (
                task["policy"].get("workspace_digest") != workspace["digest"]
                or PERMISSIONS[operation.tool] not in workspace["permissions"]
            ):
                raise WorkspaceDenied()
            step = (
                c.execute(
                    select(steps).where(
                        steps.c.id == step_id,
                        steps.c.task_id == task_id,
                        steps.c.status == "STARTED",
                    )
                )
                .mappings()
                .first()
            )
            if step is None:
                raise Conflict("Step is not dispatchable")
            self.authorization(c, task, operation.model_dump())
            existing = (
                c.execute(select(jobs).where(jobs.c.step_id == step_id).with_for_update())
                .mappings()
                .first()
            )
            if existing:
                if existing["operation"] != operation.model_dump():
                    raise Conflict("Step payload changed")
                if existing["status"] == "COMPLETED":
                    return dict(existing)
                if existing["task_token"] != token:
                    c.execute(
                        update(jobs)
                        .where(jobs.c.id == existing["id"])
                        .values(
                            task_token=token,
                            status="QUEUED",
                            controller_token=None,
                            controller_until=None,
                        )
                    )
                return dict(existing)
            job = {
                "id": str(uuid4()),
                "task_id": task_id,
                "step_id": step_id,
                "workspace_id": workspace["id"],
                "task_token": token,
                "operation": operation.model_dump(),
                "status": "QUEUED",
                "attempts": 0,
                "created_at": self.store.now(c),
            }
            c.execute(insert(jobs).values(**job))
            self.store._event(
                c,
                task,
                "SANDBOX_QUEUED",
                {"job_id": job["id"], "step_id": step_id, "workspace_sha256": workspace["digest"]},
            )
            self.store._save(c, task)
            return job

    def poll(self, task_id, token, job_id):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, task_id, token)
            workspace = self.workspace(c, task["workspace_ref"], task)
            row = (
                c.execute(select(jobs).where(jobs.c.id == job_id, jobs.c.task_id == task_id))
                .mappings()
                .one()
            )
            if PERMISSIONS[row["operation"]["tool"]] not in workspace["permissions"]:
                raise WorkspaceDenied()
            self.authorization(c, task, row["operation"])
            return Result.model_validate(row["result"]) if row["status"] == "COMPLETED" else None

    async def invoke(self, task_id, token, step_id, operation):
        job = await asyncio.to_thread(self.request, task_id, token, step_id, operation)
        while True:
            result = await asyncio.to_thread(self.poll, task_id, token, job["id"])
            if result is not None:
                return result.model_dump()
            await asyncio.sleep(0.05)

    def claim(self, image_digest, lease_seconds=10, *, tools=None):
        tools = tools or ("repo_list", "repo_read", "repo_search", "repo_patch")
        with self.store.engine.begin() as c:
            now = self.store.now(c)
            candidate = (
                c.execute(
                    select(jobs.c.id, jobs.c.task_id)
                    .join(tasks, tasks.c.id == jobs.c.task_id)
                    .where(
                        tasks.c.state == "RUNNING",
                        tasks.c.lease_token == jobs.c.task_token,
                        tasks.c.lease_until > now,
                        tasks.c.deadline > now,
                        jobs.c.operation["tool"].as_string().in_(tools),
                        (jobs.c.status == "QUEUED")
                        | ((jobs.c.status == "RUNNING") & (jobs.c.controller_until < now)),
                    )
                    .order_by(jobs.c.created_at)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if candidate is None:
                return None
            task = self.store._row(c, candidate["task_id"])
            row = (
                c.execute(
                    select(jobs)
                    .where(jobs.c.id == candidate["id"])
                    .with_for_update(skip_locked=True)
                )
                .mappings()
                .first()
            )
            if row is None:
                return None
            job = dict(row)
            if (
                task["state"] != "RUNNING"
                or task["lease_token"] != job["task_token"]
                or task["lease_until"] <= self.store.now(c)
                or (job["status"] == "RUNNING" and job["controller_until"] >= self.store.now(c))
                or job["status"] not in {"QUEUED", "RUNNING"}
            ):
                return None
            try:
                workspace = self.workspace(c, job["workspace_id"], task)
            except WorkspaceDenied:
                c.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(
                        status="COMPLETED",
                        result={
                            "ok": False,
                            "error": "workspace_policy_denied",
                            "data": {},
                            "isolation": {},
                        },
                    )
                )
                return None
            if (
                workspace["digest"] != task["policy"].get("workspace_digest")
                or PERMISSIONS[job["operation"]["tool"]] not in workspace["permissions"]
            ):
                c.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(
                        status="COMPLETED", result={"ok": False, "error": "workspace_policy_denied"}
                    )
                )
                return None
            if job["attempts"] >= min(3, task["limits"]["max_retries"] + 1):
                c.execute(
                    update(jobs)
                    .where(jobs.c.id == job["id"])
                    .values(
                        status="COMPLETED",
                        result={
                            "ok": False,
                            "error": "sandbox_retry_limit",
                            "data": {},
                            "isolation": {},
                        },
                    )
                )
                return None
            try:
                authorization = self.authorization(c, task, job["operation"], image_digest)
            except WorkspaceDenied:
                return None
            job.update(
                status="RUNNING",
                controller_token=str(uuid4()),
                controller_until=now + lease_seconds,
                attempts=job["attempts"] + 1,
                image_digest=image_digest,
            )
            c.execute(update(jobs).where(jobs.c.id == job["id"]).values(**job))
            return {
                **job,
                "files": workspace["files"],
                "digest": workspace["digest"],
                **authorization,
            }

    def heartbeat(self, job, lease_seconds=10):
        with self.store.engine.begin() as c:
            try:
                task = self.store._owned(c, job["task_id"], job["task_token"])
            except (LostLease, NotFound):
                return False
            if task["deadline"] <= self.store.now(c):
                return False
            try:
                workspace = self.workspace(c, job["workspace_id"], task)
            except WorkspaceDenied:
                return False
            if PERMISSIONS[job["operation"]["tool"]] not in workspace["permissions"]:
                return False
            try:
                self.authorization(c, task, job["operation"], job["image_digest"])
            except WorkspaceDenied:
                return False
            result = c.execute(
                update(jobs)
                .where(
                    jobs.c.id == job["id"],
                    jobs.c.controller_token == job["controller_token"],
                    jobs.c.status == "RUNNING",
                    jobs.c.controller_until > self.store.now(c),
                )
                .values(controller_until=self.store.now(c) + lease_seconds)
            )
            return result.rowcount == 1

    def finish(self, job, result: Result):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, job["task_id"], job["task_token"])
            if task["deadline"] <= self.store.now(c):
                raise LostLease()
            workspace = self.workspace(c, job["workspace_id"], task)
            if PERMISSIONS[job["operation"]["tool"]] not in workspace["permissions"]:
                raise WorkspaceDenied()
            authorization = self.authorization(c, task, job["operation"], job["image_digest"])
            owned = c.execute(
                select(jobs)
                .where(
                    jobs.c.id == job["id"],
                    jobs.c.controller_token == job["controller_token"],
                    jobs.c.status == "RUNNING",
                    jobs.c.controller_until > self.store.now(c),
                )
                .with_for_update()
            ).first()
            if not owned:
                raise LostLease()
            result = validate_result(Operation.model_validate(job["operation"]), result)
            if result.candidate_ref is not None:
                raise WorkspaceDenied()
            if (
                result.ok
                and job["operation"]["tool"] == "repo_git_status"
                and (
                    result.data["baseline_sha256"] != authorization["git_baseline_sha256"]
                    or result.data["candidate_sha256"] != authorization["git_candidate_sha256"]
                )
            ):
                raise WorkspaceDenied()
            if result.ok and job["operation"]["tool"] == "repo_test":
                expected = authorization["binding"]
                if (
                    result.data["request_ref"] != authorization["request_ref"]
                    or result.data["binding_sha256"] != authorization["binding_sha256"]
                    or result.data["image_digest"] != expected["image_digest"]
                    or result.data["baseline"]["source_sha256"] != expected["base_sha256"]
                    or result.data["candidate"]["source_sha256"] != expected["candidate_sha256"]
                    or any(
                        result.data[key]["plan_sha256"] != expected["plan_sha256"]
                        for key in ("baseline", "candidate")
                    )
                ):
                    raise WorkspaceDenied()
            if result.ok and job["operation"]["tool"] == "repo_patch":
                cid = record_candidate(
                    c,
                    task,
                    job["step_id"],
                    workspace,
                    result.data,
                    self.store.now(c),
                    job["operation"]["arguments"].get("parent_candidate_ref"),
                )
                result = Result.model_validate({**result.model_dump(), "candidate_ref": cid})
                self.store._event(
                    c, task, "CANDIDATE_PROPOSED", {"candidate_ref": cid, "source_executed": False}
                )
            row = c.execute(
                update(jobs)
                .where(
                    jobs.c.id == job["id"],
                    jobs.c.controller_token == job["controller_token"],
                    jobs.c.status == "RUNNING",
                    jobs.c.controller_until > self.store.now(c),
                )
                .values(status="COMPLETED", result=result.model_dump())
            )
            if row.rowcount != 1:
                raise LostLease()
            self.store._event(
                c,
                task,
                "SANDBOX_COMPLETED",
                {
                    "job_id": job["id"],
                    "step_id": job["step_id"],
                    "image_digest": job["image_digest"],
                    "ok": result.ok,
                },
            )
            self.store._save(c, task)
