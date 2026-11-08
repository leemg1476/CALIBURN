"""PostgreSQL-authorized review lifecycle. No execution, Docker or model approval."""

import re
from uuid import uuid4

from sqlalchemy import insert, select, text, update

from caliburn.policy.contracts import REVIEW_TOOL_DIGEST, ReviewArgs, ReviewResult, digest
from caliburn.policy.schema import candidates, decisions, plans, requests, reviewers, revocations
from caliburn.runtime.schema import runs, tasks
from caliburn.runtime.store import NotFound
from caliburn.sandbox.contracts import WORKSPACE_DIGEST, Bundle
from caliburn.sandbox.schema import jobs, workspaces


class ReviewDenied(Exception):
    pass


def role(c):
    if c.dialect.name == "postgresql":
        return c.scalar(text("SELECT current_user"))
    return "sqlite-no-review-authority"


def candidate_source(c, task, workspace, parent_id):
    """Bounded immutable ancestry; never accept another task's candidate as input."""
    parent = None
    seen = set()
    current = parent_id
    while current is not None:
        if current in seen or len(seen) >= 31:
            raise ReviewDenied("Candidate ancestry limit")
        seen.add(current)
        row = (
            c.execute(
                select(candidates).where(
                    candidates.c.id == current,
                    candidates.c.task_id == task["id"],
                    candidates.c.workspace_id == workspace["id"],
                    candidates.c.actor == task["actor"],
                    candidates.c.tenant == task["tenant"],
                )
            )
            .mappings()
            .first()
        )
        if (
            not row
            or row["base_digest"] != workspace["digest"]
            or Bundle(files=row["files"]).digest() != row["artifact_digest"]
        ):
            raise ReviewDenied("Candidate parent unavailable or changed")
        if parent is None:
            parent = row
        current = row["parent_id"]
    return dict(parent["files"]) if parent else dict(workspace["files"])


def record_candidate(c, task, step_id, workspace, patch, now, parent_id=None):
    """Called only after a sandbox patch result is validated, in its commit transaction."""
    files = candidate_source(c, task, workspace, parent_id)
    original = files[patch["path"]]
    import hashlib

    if (
        patch["base_sha256"] != hashlib.sha256(original.encode()).hexdigest()
        or patch["candidate_sha256"] != hashlib.sha256(patch["candidate"].encode()).hexdigest()
        or patch["approved"]
        or patch["executable"]
    ):
        raise ReviewDenied("Invalid candidate evidence")
    files[patch["path"]] = patch["candidate"]
    bundle = Bundle(files=files)
    cid = str(uuid4())
    c.execute(
        insert(candidates).values(
            id=cid,
            parent_id=parent_id,
            task_id=task["id"],
            step_id=step_id,
            workspace_id=workspace["id"],
            actor=task["actor"],
            tenant=task["tenant"],
            creator_role=role(c),
            base_digest=workspace["digest"],
            artifact_digest=bundle.digest(),
            files=bundle.files,
            patch=patch,
            created_at=now,
        )
    )
    return cid


class ReviewPolicy:
    def __init__(self, store):
        self.store = store

    def executed(self, c, request_id):
        attempts = (
            c.execute(
                select(jobs.c.result, jobs.c.attempts).where(
                    jobs.c.operation["tool"].as_string() == "repo_test",
                    jobs.c.operation["arguments"]["request_ref"].as_string() == request_id,
                )
            )
            .mappings()
            .all()
        )
        if any(
            row["result"] and row["result"].get("data", {}).get("source_executed")
            for row in attempts
        ):
            return True
        # A fenced/crashed dispatch might have started source without a committed result.
        return None if any(row["attempts"] > 0 for row in attempts) else False

    def _owner(self, c):
        if c.dialect.name != "postgresql":
            raise ReviewDenied("Review authority requires PostgreSQL")
        allowed = c.scalar(
            text("""SELECT r.rolsuper OR n.nspowner=r.oid FROM pg_roles r,
            pg_namespace n WHERE r.rolname=current_user AND n.nspname=current_schema()""")
        )
        if not allowed:
            raise ReviewDenied("Operator-owned connection required")

    def configure_reviewer(self, db_role, principal, tenant="development"):
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", db_role):
            raise ValueError("Invalid database role")
        if not 1 <= len(principal) <= 80:
            raise ValueError("Invalid reviewer principal")
        with self.store.engine.begin() as c:
            self._owner(c)
            if not c.scalar(
                text("SELECT EXISTS(SELECT 1 FROM pg_roles WHERE rolname=:name)"), {"name": db_role}
            ):
                raise ReviewDenied("Provision a separate reviewer role outside the agent first")
            existing = (
                c.execute(select(reviewers).where(reviewers.c.db_role == db_role))
                .mappings()
                .first()
            )
            if existing and (
                existing["principal"] != principal
                or existing["tenant"] != tenant
                or existing["enabled"] != "yes"
            ):
                raise ReviewDenied("Explicit reviewer offboarding/reconfiguration required")
            if not existing:
                c.execute(
                    insert(reviewers).values(
                        db_role=db_role, principal=principal, tenant=tenant, enabled="yes"
                    )
                )
            quote = c.dialect.identifier_preparer.quote
            schema = quote(c.scalar(text("SELECT current_schema()")))
            target = quote(db_role)
            c.execute(text(f"GRANT USAGE ON SCHEMA {schema} TO {target}"))
            names = [
                "policy_candidates",
                "policy_test_plans",
                "policy_reviewers",
                "policy_review_requests",
                "policy_review_decisions",
                "policy_review_revocations",
                "sandbox_workspaces",
                "sandbox_jobs",
                "runtime_tasks",
                "runtime_runs",
            ]
            for name in names:
                c.execute(text(f"GRANT SELECT ON {schema}.{quote(name)} TO {target}"))
            for name in ["policy_review_decisions", "policy_review_revocations", "runtime_events"]:
                c.execute(text(f"GRANT INSERT ON {schema}.{quote(name)} TO {target}"))
            c.execute(
                text(
                    f"GRANT UPDATE (state,error,sequence,updated_at,lease_token,lease_owner,lease_until) ON {schema}.runtime_tasks TO {target}"
                )
            )
            c.execute(text(f"GRANT UPDATE (outcome,ended_at) ON {schema}.runtime_runs TO {target}"))

    def register_plan(self, workspace_id, files, image_digest, ttl_seconds=3600):
        bundle = Bundle(files=files)
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image_digest):
            raise ValueError("Immutable image required")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 86400:
            raise ValueError("Invalid plan TTL")
        with self.store.engine.begin() as c:
            self._owner(c)
            workspace = (
                c.execute(select(workspaces).where(workspaces.c.id == workspace_id))
                .mappings()
                .first()
            )
            if not workspace:
                raise NotFound()
            now = self.store.now(c)
            pid = str(uuid4())
            c.execute(
                insert(plans).values(
                    id=pid,
                    workspace_id=workspace_id,
                    tenant=workspace["tenant"],
                    owner_role=role(c),
                    files=bundle.files,
                    digest=bundle.digest(),
                    image_digest=image_digest,
                    created_at=now,
                    expires_at=min(now + ttl_seconds, workspace["expires_at"]),
                )
            )
            return pid

    def _binding(self, c, task, candidate_id, plan_id):
        candidate = (
            c.execute(
                select(candidates).where(
                    candidates.c.id == candidate_id,
                    candidates.c.task_id == task["id"],
                    candidates.c.actor == task["actor"],
                    candidates.c.tenant == task["tenant"],
                )
            )
            .mappings()
            .first()
        )
        plan = (
            c.execute(
                select(plans).where(
                    plans.c.id == plan_id,
                    plans.c.workspace_id == task["workspace_ref"],
                    plans.c.tenant == task["tenant"],
                )
            )
            .mappings()
            .first()
        )
        workspace = (
            c.execute(
                select(workspaces).where(
                    workspaces.c.id == task["workspace_ref"],
                    workspaces.c.actor == task["actor"],
                    workspaces.c.tenant == task["tenant"],
                    workspaces.c.status == "ACTIVE",
                    workspaces.c.expires_at > self.store.now(c),
                )
            )
            .mappings()
            .first()
        )
        if (
            not candidate
            or not plan
            or not workspace
            or plan["expires_at"] <= self.store.now(c)
            or "request_review" not in workspace["permissions"]
        ):
            raise ReviewDenied("Review scope unavailable")
        if (
            Bundle(files=candidate["files"]).digest() != candidate["artifact_digest"]
            or Bundle(files=plan["files"]).digest() != plan["digest"]
            or Bundle(files=workspace["files"]).digest() != candidate["base_digest"]
            or workspace["digest"] != task["policy"].get("workspace_digest")
        ):
            raise ReviewDenied("Review artifact changed")
        binding = {
            "version": "sandbox-review-v3",
            "scope": "sandbox_test_only",
            "execution_permitted": "execute_reviewed_tests" in workspace["permissions"],
            "task_id": task["id"],
            "actor": task["actor"],
            "tenant": task["tenant"],
            "workspace_ref": workspace["id"],
            "base_sha256": candidate["base_digest"],
            "candidate_ref": candidate["id"],
            "parent_candidate_ref": candidate["parent_id"],
            "patch_source_sha256": Bundle(
                files=candidate_source(c, task, workspace, candidate["parent_id"])
            ).digest(),
            "candidate_sha256": candidate["artifact_digest"],
            "plan_ref": plan["id"],
            "plan_sha256": plan["digest"],
            "image_digest": plan["image_digest"],
            "workspace_tool_sha256": WORKSPACE_DIGEST,
            "review_tool_sha256": REVIEW_TOOL_DIGEST,
        }
        return binding, candidate, plan, workspace

    def authorize_test(self, c, task, request_id, image_digest=None):
        """Rechecked at request/dispatch/heartbeat/poll/result; never accepts caller artifacts."""
        if c.dialect.name != "postgresql" or "repo_test" not in task["policy"]["tools"]:
            raise ReviewDenied("Reviewed execution unavailable")
        request = (
            c.execute(
                select(requests).where(
                    requests.c.id == request_id, requests.c.task_id == task["id"]
                )
            )
            .mappings()
            .first()
        )
        if not request or self._state(c, request, task) != "APPROVED_FOR_SANDBOX_TEST":
            raise ReviewDenied("Independent review required")
        binding, candidate, plan, workspace = self._binding(
            c, task, request["candidate_id"], request["plan_id"]
        )
        if not binding["execution_permitted"] or (
            image_digest is not None and plan["image_digest"] != image_digest
        ):
            raise ReviewDenied("Execution grant/image denied")
        return {
            "request_ref": request_id,
            "binding_sha256": request["digest"],
            "binding": binding,
            "base_files": workspace["files"],
            "candidate_files": candidate["files"],
            "plan_files": plan["files"],
        }

    def _state(self, c, request, task):
        binding, _, _, _ = self._binding(c, task, request["candidate_id"], request["plan_id"])
        if binding != request["binding"] or digest(binding) != request["digest"]:
            raise ReviewDenied("Review binding changed")
        if self.store.now(c) >= min(request["expires_at"], task["deadline"]):
            return "EXPIRED"
        if c.execute(select(revocations).where(revocations.c.request_id == request["id"])).first():
            return "REVOKED"
        decision = (
            c.execute(select(decisions).where(decisions.c.request_id == request["id"]))
            .mappings()
            .first()
        )
        if not decision:
            return "PENDING"
        reviewer = (
            c.execute(
                select(reviewers).where(
                    reviewers.c.db_role == decision["reviewer_role"],
                    reviewers.c.tenant == task["tenant"],
                    reviewers.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        if not reviewer or decision["binding_digest"] != request["digest"]:
            return "REVOKED"
        if decision["expires_at"] <= self.store.now(c):
            return "EXPIRED"
        return "APPROVED_FOR_SANDBOX_TEST" if decision["decision"] == "APPROVE" else "REJECTED"

    def ensure(self, task_id, token, args: ReviewArgs, call_key):
        with self.store.engine.begin() as c:
            task = self.store._owned(c, task_id, token)
            binding, _, plan, workspace = self._binding(c, task, args.candidate_ref, args.plan_ref)
            existing = (
                c.execute(
                    select(requests).where(
                        requests.c.task_id == task_id, requests.c.call_key == call_key
                    )
                )
                .mappings()
                .first()
            )
            if existing:
                if existing["digest"] != digest(binding):
                    raise ReviewDenied("Review request changed")
                state = self._state(c, existing, task)
                if state == "APPROVED_FOR_SANDBOX_TEST":
                    return ReviewResult.model_validate(
                        {
                            "ok": True,
                            "data": {
                                "review_status": state,
                                "request_ref": existing["id"],
                                "binding_sha256": existing["digest"],
                                "scope": "sandbox_test_only",
                                "source_executed": False,
                            },
                        }
                    ).model_dump()
                if state != "PENDING":
                    raise ReviewDenied("Review is not approved")
            else:
                existing = {
                    "id": str(uuid4()),
                    "task_id": task_id,
                    "candidate_id": args.candidate_ref,
                    "plan_id": args.plan_ref,
                    "call_key": call_key,
                    "creator_role": role(c),
                    "binding": binding,
                    "digest": digest(binding),
                    "created_at": self.store.now(c),
                    "expires_at": min(
                        task["deadline"], plan["expires_at"], workspace["expires_at"]
                    ),
                }
                c.execute(insert(requests).values(**existing))
            self.store._event(
                c,
                task,
                "REVIEW_REQUESTED",
                {
                    "request_ref": existing["id"],
                    "binding_sha256": existing["digest"],
                    "scope": "sandbox_test_only",
                },
            )
            self.store._end(c, task, "WAITING_APPROVAL")
            return None

    def _reviewer(self, c, request, task):
        if c.dialect.name != "postgresql":
            raise ReviewDenied("PostgreSQL review authority required")
        caller = role(c)
        reviewer = (
            c.execute(
                select(reviewers).where(
                    reviewers.c.db_role == caller,
                    reviewers.c.tenant == task["tenant"],
                    reviewers.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        candidate = (
            c.execute(select(candidates).where(candidates.c.id == request["candidate_id"]))
            .mappings()
            .one()
        )
        if (
            not reviewer
            or caller in {request["creator_role"], candidate["creator_role"]}
            or reviewer["principal"] == task["actor"]
        ):
            raise ReviewDenied("Independent reviewer required")
        return caller, reviewer

    def _persist_state(self, c, task, state, error=None, reviewer=None):
        task.update(state=state, error=error, lease_token=None, lease_owner=None, lease_until=None)
        self.store._event(c, task, "REVIEW_" + state, {"reason": error, "reviewer_role": reviewer})
        c.execute(
            update(tasks)
            .where(tasks.c.id == task["id"])
            .values(
                **{
                    key: task[key]
                    for key in [
                        "state",
                        "error",
                        "lease_token",
                        "lease_owner",
                        "lease_until",
                        "sequence",
                        "updated_at",
                    ]
                }
            )
        )
        if state != "QUEUED" and task.get("run_id"):
            c.execute(
                update(runs)
                .where(runs.c.id == task["run_id"])
                .values(outcome=state, ended_at=self.store.now(c))
            )

    def decide(self, request_id, expected_digest, decision, ttl_seconds=600):
        if decision not in {"APPROVE", "REJECT"}:
            raise ValueError("Invalid review decision")
        if type(ttl_seconds) is not int or not 1 <= ttl_seconds <= 3600:
            raise ValueError("Invalid review TTL")
        with self.store.engine.begin() as c:
            request = (
                c.execute(select(requests).where(requests.c.id == request_id)).mappings().first()
            )
            if not request:
                raise NotFound()
            task = self.store._row(c, request["task_id"])
            caller, _ = self._reviewer(c, request, task)
            if task["state"] != "WAITING_APPROVAL" or request["digest"] != expected_digest:
                raise ReviewDenied("Task/binding is not reviewable")
            if self._state(c, request, task) != "PENDING":
                raise ReviewDenied("Review has expired or already decided")
            now = self.store.now(c)
            c.execute(
                insert(decisions).values(
                    id=str(uuid4()),
                    request_id=request_id,
                    decision=decision,
                    reviewer_role=caller,
                    binding_digest=expected_digest,
                    created_at=now,
                    expires_at=min(request["expires_at"], now + ttl_seconds),
                )
            )
            self._persist_state(
                c,
                task,
                "QUEUED" if decision == "APPROVE" else "FAILED",
                None if decision == "APPROVE" else "review_rejected",
                caller,
            )
            return request["id"]

    def revoke(self, request_id):
        with self.store.engine.begin() as c:
            request = (
                c.execute(select(requests).where(requests.c.id == request_id)).mappings().first()
            )
            if not request:
                raise NotFound()
            task = self.store._row(c, request["task_id"])
            caller, _ = self._reviewer(c, request, task)
            if not c.execute(select(decisions).where(decisions.c.request_id == request_id)).first():
                raise ReviewDenied("No decision to revoke")
            c.execute(
                insert(revocations).values(
                    request_id=request_id, reviewer_role=caller, created_at=self.store.now(c)
                )
            )
            if task["state"] not in {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}:
                self._persist_state(c, task, "FAILED", "review_revoked", caller)

    def inspect(self, request_id):
        """Explicit reviewer-only materialization of exact untrusted review artifacts."""
        with self.store.engine.begin() as c:
            request = (
                c.execute(select(requests).where(requests.c.id == request_id)).mappings().first()
            )
            if not request:
                raise NotFound()
            task = self.store._row(c, request["task_id"])
            self._reviewer(c, request, task)
            binding, candidate, plan, _ = self._binding(
                c, task, request["candidate_id"], request["plan_id"]
            )
            if binding != request["binding"] or digest(binding) != request["digest"]:
                raise ReviewDenied("Review artifact changed")
            return {
                "request_ref": request_id,
                "binding": binding,
                "binding_sha256": request["digest"],
                "status": self._state(c, request, task),
                "candidate_files": candidate["files"],
                "patch": candidate["patch"],
                "test_plan_files": plan["files"],
                "source_executed": self.executed(c, request_id),
            }

    def views(self, task_id, actor="development-service", tenant="development"):
        with self.store.engine.begin() as c:
            task = self.store._row(c, task_id, actor, tenant)
            result = []
            for req in c.execute(select(requests).where(requests.c.task_id == task_id)).mappings():
                try:
                    state = self._state(c, req, task)
                except ReviewDenied:
                    state = "INVALIDATED"
                result.append(
                    {
                        "id": req["id"],
                        "binding": req["binding"],
                        "binding_sha256": req["digest"],
                        "status": state,
                        "expires_at": req["expires_at"],
                        "source_executed": self.executed(c, req["id"]),
                    }
                )
            return result
