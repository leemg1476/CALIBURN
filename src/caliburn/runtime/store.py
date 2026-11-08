"""Transactional PostgreSQL queue with fencing, checkpoints and append-only events."""

import hashlib
import json
import time
from functools import lru_cache
from uuid import uuid4

from sqlalchemy import create_engine, func, insert, select, update
from sqlalchemy.exc import IntegrityError

from caliburn.policy.contracts import REVIEW_TOOL_DIGEST
from caliburn.policy.schema import metadata as policy_metadata
from caliburn.runtime.contracts import Submit
from caliburn.runtime.schema import attachments, events, runs, steps, tasks
from caliburn.sandbox.contracts import PERMISSIONS, WORKSPACE_DIGEST
from caliburn.sandbox.schema import workspaces
from caliburn.tool_factory.contracts import FACTORY_DIGEST, INPUTS
from caliburn.tool_factory.execution_contracts import EXEC_DIGEST, EXEC_INPUTS
from caliburn.tool_factory.schema import metadata as factory_metadata
from caliburn.tools import CURATED_DIGEST

assert policy_metadata is tasks.metadata
assert factory_metadata is tasks.metadata

TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "TIMED_OUT"}


class NotFound(Exception):
    pass


class Conflict(Exception):
    pass


class LostLease(Exception):
    pass


class Store:
    def __init__(self, url: str):
        self.engine = create_engine(url, pool_pre_ping=True)

    def now(self, c):
        if self.engine.dialect.name == "postgresql":
            return float(c.scalar(select(func.extract("epoch", func.clock_timestamp()))))
        return time.time()

    def _row(self, c, task_id, actor=None, tenant=None):
        q = select(tasks).where(tasks.c.id == task_id)
        if actor is not None:
            q = q.where(tasks.c.actor == actor, tasks.c.tenant == tenant)
        row = c.execute(q.with_for_update()).mappings().first()
        if not row:
            raise NotFound()
        return dict(row)

    def _event(self, c, t, kind, payload=None):
        t["sequence"] += 1
        t["updated_at"] = self.now(c)
        c.execute(
            insert(events).values(
                task_id=t["id"],
                sequence=t["sequence"],
                timestamp=t["updated_at"],
                actor=t["actor"],
                type=kind,
                run_id=t.get("run_id"),
                payload=payload or {},
            )
        )

    def _save(self, c, t):
        c.execute(update(tasks).where(tasks.c.id == t["id"]).values(**t))

    def submit(
        self,
        request: Submit,
        actor="development-service",
        tenant="development",
        *,
        allow_capability_proposals=False,
        allow_capability_checks=False,
        allow_factory_execution=False,
        allow_registry_invocation=False,
    ):
        body = request.model_dump(exclude={"idempotency_key"}, exclude_none=True)
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        key = request.idempotency_key or str(uuid4())
        try:
            with self.engine.begin() as c:
                now = self.now(c)
                workspace = None
                if request.workspace_ref:
                    workspace = (
                        c.execute(
                            select(workspaces).where(
                                workspaces.c.id == request.workspace_ref,
                                workspaces.c.actor == actor,
                                workspaces.c.tenant == tenant,
                                workspaces.c.status == "ACTIVE",
                                workspaces.c.expires_at > now,
                            )
                        )
                        .mappings()
                        .first()
                    )
                    if workspace is None:
                        raise NotFound()
                t = {
                    "id": str(uuid4()),
                    "actor": actor,
                    "tenant": tenant,
                    "idempotency_key": key,
                    "request_hash": digest,
                    "prompt": request.prompt,
                    "workspace_ref": request.workspace_ref,
                    "state": "QUEUED",
                    "created_at": now,
                    "updated_at": now,
                    "limits": request.limits.model_dump(),
                    "policy": {
                        "version": "m1-static-v1",
                        "tool_digest": CURATED_DIGEST,
                        "tools": ["add_numbers", "utc_now"],
                        "external_writes": False,
                        "generated_code": False,
                    },
                    "messages": [{"role": "user", "content": request.prompt}],
                    "sequence": 0,
                    "model_calls": 0,
                    "tool_calls": 0,
                    "reserved_tokens": 0,
                    "reserved_cost": 0.0,
                }
                if workspace is not None:
                    t["policy"].update(
                        workspace_digest=workspace["digest"],
                        workspace_tools_digest=WORKSPACE_DIGEST,
                        reviewed_test_execution="execute_reviewed_tests"
                        in workspace["permissions"],
                        git_image_digest=workspace["provenance"].get("git_image_digest"),
                    )
                    t["policy"]["tools"] += [
                        name
                        for name, permission in PERMISSIONS.items()
                        if permission in workspace["permissions"]
                    ]
                if allow_capability_proposals:
                    t["policy"]["tools"] += [name for name in INPUTS if name != "capability_check"]
                    t["policy"]["factory_digest"] = FACTORY_DIGEST
                if allow_capability_checks:
                    t["policy"]["tools"].append("capability_check")
                    t["policy"]["factory_digest"] = FACTORY_DIGEST
                if allow_factory_execution:
                    t["policy"]["tools"] += list(EXEC_INPUTS)
                    t["policy"].update(exec_digest=EXEC_DIGEST, factory_digest=FACTORY_DIGEST)
                if workspace is not None and "request_review" in workspace["permissions"]:
                    t["policy"]["tools"].append("repo_request_review")
                    t["policy"]["review_tool_digest"] = REVIEW_TOOL_DIGEST
                if allow_registry_invocation:
                    from caliburn.tool_factory.release_contracts import release_digest
                    from caliburn.tool_factory.release_service import ReleaseService

                    registry = ReleaseService(self)
                    names = request.capabilities
                    pins = registry.select(c, names, actor, tenant)
                    if pins:
                        t["policy"].update(
                            capabilities=pins,
                            registry_digest=release_digest(),
                            generated_code="qualified_internal_only",
                        )
                        t["policy"]["tools"] += list(pins)
                elif request.capabilities:
                    from caliburn.tool_factory.release_contracts import ReleaseDenied

                    raise ReleaseDenied()
                c.execute(insert(tasks).values(**t))
                self._event(
                    c, t, "TASK_CREATED", {"input_sha256": digest, "policy": "m1-static-v1"}
                )
                self._save(c, t)
                return t
        except IntegrityError:
            with self.engine.connect() as c:
                row = (
                    c.execute(
                        select(tasks).where(
                            tasks.c.actor == actor,
                            tasks.c.tenant == tenant,
                            tasks.c.idempotency_key == key,
                        )
                    )
                    .mappings()
                    .first()
                )
                if row is None:
                    raise
                if row["request_hash"] != digest:
                    raise Conflict("Idempotency key reused")
                return dict(row)

    def get(self, task_id, actor="development-service", tenant="development"):
        with self.engine.begin() as c:
            return self._row(c, task_id, actor, tenant)

    def replay(self, task_id, after=0, actor="development-service", tenant="development"):
        with self.engine.begin() as c:
            self._row(c, task_id, actor, tenant)
            return [
                dict(r)
                for r in c.execute(
                    select(events)
                    .where(events.c.task_id == task_id, events.c.sequence > after)
                    .order_by(events.c.sequence)
                    .limit(500)
                ).mappings()
            ]

    def history(
        self,
        task_id,
        after_step=0,
        run_offset=0,
        limit=50,
        actor="development-service",
        tenant="development",
    ):
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or type(after_step) is not int
            or after_step < 0
            or type(run_offset) is not int
            or not 0 <= run_offset <= 100000
        ):
            raise ValueError("Invalid history cursor")
        with self.engine.begin() as c:
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
            page = (
                c.execute(
                    select(steps)
                    .where(steps.c.task_id == task_id, steps.c.ordinal > after_step)
                    .order_by(steps.c.ordinal)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )
            run_page = (
                c.execute(
                    select(runs)
                    .where(runs.c.task_id == task_id)
                    .order_by(runs.c.started_at, runs.c.id)
                    .offset(run_offset)
                    .limit(limit + 1)
                )
                .mappings()
                .all()
            )

            def sha(value):
                return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()

            def tool_name(row):
                function = row["input"].get("function")
                name = function.get("name") if isinstance(function, dict) else None
                return name[:100] if isinstance(name, str) else None

            return {
                "limits": task["limits"],
                "deadline": task["deadline"],
                "steps": [
                    {
                        "id": row["id"],
                        "ordinal": row["ordinal"],
                        "run_id": row["run_id"],
                        "kind": row["kind"],
                        "status": row["status"],
                        "attempts": row["attempts"],
                        "tool_name": tool_name(row),
                        "input_sha256": sha(row["input"]),
                        "output_sha256": sha(row["output"]) if row["output"] is not None else None,
                    }
                    for row in page[:limit]
                ],
                "runs": [
                    {key: row[key] for key in ("id", "worker", "started_at", "ended_at", "outcome")}
                    for row in run_page[:limit]
                ],
                "next_step": page[limit - 1]["ordinal"] if len(page) > limit else None,
                "next_run_offset": run_offset + limit if len(run_page) > limit else None,
            }

    def _end(self, c, t, state, error=None):
        t.update(state=state, error=error, lease_token=None, lease_owner=None, lease_until=None)
        if t.get("run_id"):
            c.execute(
                update(runs)
                .where(runs.c.id == t["run_id"])
                .values(ended_at=self.now(c), outcome=state)
            )
        self._event(c, t, "TASK_" + state, {"reason": error} if error else {})
        self._save(c, t)

    def control(self, task_id, action, actor="development-service", tenant="development"):
        with self.engine.begin() as c:
            t = self._row(c, task_id, actor, tenant)
            if action == "cancel" and t["state"] not in TERMINAL:
                self._end(c, t, "CANCELLED")
            elif action == "pause" and t["state"] in {"QUEUED", "RUNNING"}:
                self._end(c, t, "PAUSED")
            elif action == "resume" and t["state"] == "PAUSED":
                t["state"] = "QUEUED"
                self._event(c, t, "TASK_RESUMED")
                self._save(c, t)
            elif action == "cancel" and t["state"] == "CANCELLED":
                pass
            else:
                raise Conflict("Invalid task transition")
            return t

    def claim(self, worker, lease_seconds=15):
        with self.engine.begin() as c:
            now = self.now(c)
            from caliburn.tool_factory.qualification import Qualification

            waiting = (
                c.execute(
                    select(tasks)
                    .where(
                        tasks.c.state == "WAITING_APPROVAL",
                        tasks.c.deadline > now,
                        Qualification.wakeable(now),
                    )
                    .order_by(tasks.c.updated_at)
                    .with_for_update(skip_locked=True)
                    .limit(20)
                )
                .mappings()
                .all()
            )
            for pending in waiting:
                Qualification(self).wake(c, dict(pending))
            overdue = (
                c.execute(
                    select(tasks)
                    .where(tasks.c.state == "WAITING_APPROVAL", tasks.c.deadline <= now)
                    .with_for_update(skip_locked=True)
                    .limit(20)
                )
                .mappings()
                .all()
            )
            for row in overdue:
                self._end(c, dict(row), "TIMED_OUT", "wall_time_limit")
            q = select(tasks).where(
                (tasks.c.state == "QUEUED")
                | ((tasks.c.state == "RUNNING") & (tasks.c.lease_until < now))
            )
            row = (
                c.execute(q.order_by(tasks.c.created_at).with_for_update(skip_locked=True).limit(1))
                .mappings()
                .first()
            )
            if not row:
                return None
            t = dict(row)
            recovered = t["state"] == "RUNNING"
            if t.get("deadline") is not None and t["deadline"] <= now:
                self._end(c, t, "TIMED_OUT", "wall_time_limit")
                return None
            if recovered:
                c.execute(
                    update(runs)
                    .where(runs.c.id == t["run_id"])
                    .values(ended_at=now, outcome="LEASE_EXPIRED")
                )
            run_id, token = str(uuid4()), str(uuid4())
            c.execute(
                insert(runs).values(id=run_id, task_id=t["id"], worker=worker, started_at=now)
            )
            t.update(
                state="RUNNING",
                run_id=run_id,
                lease_token=token,
                lease_owner=worker,
                lease_until=now + lease_seconds,
                deadline=t.get("deadline") or now + t["limits"]["timeout_seconds"],
            )
            self._event(c, t, "WORKER_RECOVERED" if recovered else "RUN_STARTED")
            self._save(c, t)
            return t

    def _owned(self, c, task_id, token):
        t = self._row(c, task_id)
        if t["state"] != "RUNNING" or t["lease_token"] != token or t["lease_until"] <= self.now(c):
            raise LostLease()
        return t

    def heartbeat(self, task_id, token, lease_seconds):
        with self.engine.begin() as c:
            t = self._owned(c, task_id, token)
            if t["deadline"] <= self.now(c):
                self._end(c, t, "TIMED_OUT", "wall_time_limit")
                return False
            t["lease_until"] = self.now(c) + lease_seconds
            self._save(c, t)
            return True

    def prepare(self, task_id, token, kind, data, token_reserve=0, cost=0):
        with self.engine.begin() as c:
            t = self._owned(c, task_id, token)
            limits = t["limits"]
            if self.now(c) >= t["deadline"]:
                self._end(c, t, "TIMED_OUT", "wall_time_limit")
                return None
            pending = (
                c.execute(
                    select(steps).where(steps.c.task_id == task_id, steps.c.status == "STARTED")
                )
                .mappings()
                .first()
            )
            reason = None
            if pending and pending["attempts"] >= limits["max_retries"] + 1:
                reason = "retry_limit"
            if kind == "MODEL" and t["model_calls"] >= limits["max_steps"]:
                reason = "model_step_limit"
            if kind == "TOOL" and t["tool_calls"] >= limits["max_tool_calls"]:
                reason = "tool_call_limit"
            if t["reserved_tokens"] + token_reserve > limits["max_tokens"]:
                reason = "token_limit"
            if t["reserved_cost"] + cost > limits["max_cost"] + 1e-12:
                reason = "cost_limit"
            if reason:
                self._end(c, t, "FAILED", reason)
                return None
            field = "model_calls" if kind == "MODEL" else "tool_calls"
            t[field] += 1
            t["reserved_tokens"] += token_reserve
            t["reserved_cost"] += cost
            if pending:
                step = dict(pending)
                step["attempts"] += 1
                c.execute(
                    update(steps)
                    .where(steps.c.id == step["id"])
                    .values(attempts=step["attempts"], run_id=t["run_id"])
                )
            else:
                ordinal = (
                    c.scalar(
                        select(func.count()).select_from(steps).where(steps.c.task_id == task_id)
                    )
                    + 1
                )
                step = {
                    "id": str(uuid4()),
                    "task_id": task_id,
                    "run_id": t["run_id"],
                    "ordinal": ordinal,
                    "kind": kind,
                    "status": "STARTED",
                    "attempts": 1,
                    "input": data,
                }
                c.execute(insert(steps).values(**step))
            self._event(
                c,
                t,
                "STEP_STARTED",
                {
                    "step_id": step["id"],
                    "kind": kind,
                    "attempt": step["attempts"],
                    "policy": "m1-static-v1",
                    "tool_digest": (
                        t["policy"]["registry_digest"]
                        if data.get("function", {}).get("name")
                        in t["policy"].get("capabilities", {})
                        else EXEC_DIGEST
                        if data.get("function", {}).get("name") in EXEC_INPUTS
                        else FACTORY_DIGEST
                        if data.get("function", {}).get("name") in INPUTS
                        else WORKSPACE_DIGEST
                        if data.get("function", {}).get("name", "").startswith("repo_")
                        else CURATED_DIGEST
                    )
                    if kind == "TOOL"
                    else None,
                    "tool_name": data.get("function", {}).get("name") if kind == "TOOL" else None,
                },
            )
            self._save(c, t)
            return step

    def commit(self, task_id, token, step_id, message, final=False):
        with self.engine.begin() as c:
            t = self._owned(c, task_id, token)
            if self.now(c) >= t["deadline"]:
                self._end(c, t, "TIMED_OUT", "wall_time_limit")
                return
            step = (
                c.execute(select(steps).where(steps.c.id == step_id, steps.c.task_id == task_id))
                .mappings()
                .one()
            )
            if step["status"] != "STARTED":
                raise Conflict("Step already committed")
            c.execute(
                update(steps)
                .where(steps.c.id == step_id)
                .values(status="COMPLETED", output=message)
            )
            t["messages"] = t["messages"] + [message]
            self._event(
                c,
                t,
                "STEP_COMPLETED",
                {
                    "step_id": step_id,
                    "kind": step["kind"],
                    "output_sha256": hashlib.sha256(
                        json.dumps(message, sort_keys=True).encode()
                    ).hexdigest(),
                },
            )
            if final:
                t["result"] = message.get("content") or ""
                content = t["result"]
                c.execute(
                    insert(attachments).values(
                        id=str(uuid4()),
                        task_id=task_id,
                        sha256=hashlib.sha256(content.encode()).hexdigest(),
                        media_type="text/plain",
                        content=content,
                    )
                )
                self._end(c, t, "COMPLETED")
            else:
                self._save(c, t)

    def fail(self, task_id, token, reason, state="FAILED"):
        with self.engine.begin() as c:
            t = self._owned(c, task_id, token)
            self._end(c, t, state, reason)


@lru_cache
def get_store(url):
    return Store(url)
