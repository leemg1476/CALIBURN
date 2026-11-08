"""Durable version-pinned tool invocation; model/worker never imports tool source."""

import asyncio
from uuid import uuid4

from sqlalchemy import insert, select, update

from caliburn.runtime.schema import steps, tasks
from caliburn.runtime.store import LostLease
from caliburn.tool_factory.checks import role
from caliburn.tool_factory.contracts import digest, matches
from caliburn.tool_factory.oracle import parse_json
from caliburn.tool_factory.release_contracts import InvocationResult, ReleaseDenied
from caliburn.tool_factory.release_service import ReleaseService
from caliburn.tool_factory.schema import (
    release_executors,
    release_invocations,
    release_revocations,
    release_versions,
)


class InvocationQueue:
    def __init__(self, store):
        self.store = store
        self.service = ReleaseService(store)

    def submit(self, tid, token, step_id, name, raw):
        args = parse_json(raw)
        with self.store.engine.begin() as c:
            t = self.store._owned(c, tid, token)
            version, s, _ = self.service.authorize(c, t, name)
            if not matches(s.manifest["input_schema"], args):
                raise ValueError("Invalid registered-tool arguments")
            step = (
                c.execute(
                    select(steps).where(
                        steps.c.id == step_id,
                        steps.c.task_id == tid,
                        steps.c.kind == "TOOL",
                        steps.c.status == "STARTED",
                    )
                )
                .mappings()
                .first()
            )
            if (
                not step
                or step["input"].get("function", {}).get("name") != name
                or parse_json(step["input"]["function"]["arguments"]) != args
            ):
                raise ReleaseDenied()
            old = (
                c.execute(
                    select(release_invocations).where(release_invocations.c.step_id == step_id)
                )
                .mappings()
                .first()
            )
            if old:
                if old["release_id"] != version["id"] or old["input_sha256"] != digest(args):
                    raise ReleaseDenied()
                return old["id"]
            jid = str(uuid4())
            c.execute(
                insert(release_invocations).values(
                    id=jid,
                    task_id=tid,
                    step_id=step_id,
                    release_id=version["id"],
                    tenant=t["tenant"],
                    arguments=args,
                    input_sha256=digest(args),
                    creator_role=role(c),
                    state="QUEUED",
                    attempts=0,
                    created_at=self.store.now(c),
                )
            )
            self.store._event(
                c,
                t,
                "REGISTERED_TOOL_QUEUED",
                {
                    "invocation_id": jid,
                    "release_ref": version["id"],
                    "name": name,
                    "version": s.version,
                    "source_sha256": s.source_sha256,
                },
            )
            self.store._save(c, t)
            return jid

    def poll(self, tid, token, jid):
        with self.store.engine.begin() as c:
            t = self.store._owned(c, tid, token)
            j = (
                c.execute(
                    select(release_invocations).where(
                        release_invocations.c.id == jid,
                        release_invocations.c.task_id == tid,
                        release_invocations.c.tenant == t["tenant"],
                    )
                )
                .mappings()
                .first()
            )
            if not j:
                raise ReleaseDenied()
            step = c.execute(select(steps).where(steps.c.id == j["step_id"])).mappings().one()
            name = step["input"]["function"]["name"]
            pin = t["policy"].get("capabilities", {}).get(name)
            if not pin or pin["release_id"] != j["release_id"]:
                raise ReleaseDenied()
            if j["result"] is not None:
                if digest(j["result"]) != j["result_sha256"]:
                    raise ReleaseDenied()
                result = InvocationResult.model_validate(j["result"])
                if (
                    result.release_ref != pin["release_id"]
                    or result.version != pin["version"]
                    or result.source_sha256 != pin["source_sha256"]
                ):
                    raise ReleaseDenied()
                if result.ok:
                    self.service.authorize(c, t, name)
                return result.model_dump()
            self.service.authorize(c, t, name)
            return None

    async def invoke(self, tid, token, step_id, name, raw):
        jid = await asyncio.to_thread(self.submit, tid, token, step_id, name, raw)
        while True:
            result = await asyncio.to_thread(self.poll, tid, token, jid)
            if result is not None:
                return result
            await asyncio.sleep(0.05)

    def _error(self, pin, code):
        return InvocationResult(
            ok=False,
            release_ref=pin["release_id"],
            version=pin["version"],
            source_sha256=pin["source_sha256"],
            error=code,
        ).model_dump()

    def claim(self, image, tools=()):
        with self.store.engine.begin() as c:
            who = (
                c.execute(
                    select(release_executors).where(
                        release_executors.c.db_role == role(c), release_executors.c.enabled == "yes"
                    )
                )
                .mappings()
                .first()
            )
            if not who:
                raise ReleaseDenied()
            self.service.executor(c, who["tenant"])
            now = self.store.now(c)
            j = (
                c.execute(
                    select(release_invocations)
                    .join(tasks, tasks.c.id == release_invocations.c.task_id)
                    .join(
                        release_versions, release_versions.c.id == release_invocations.c.release_id
                    )
                    .where(
                        release_invocations.c.tenant == who["tenant"],
                        tasks.c.state == "RUNNING",
                        release_versions.c.envelope["statement"]["image_digest"].as_string()
                        == image,
                        (release_invocations.c.state == "QUEUED")
                        | (
                            (release_invocations.c.state == "RUNNING")
                            & (release_invocations.c.lease_until <= now)
                        ),
                    )
                    .order_by(release_invocations.c.created_at)
                    .with_for_update(skip_locked=True, of=release_invocations)
                    .limit(1)
                )
                .mappings()
                .first()
            )
            if not j:
                return None
            t = c.execute(select(tasks).where(tasks.c.id == j["task_id"])).mappings().one()
            step = c.execute(select(steps).where(steps.c.id == j["step_id"])).mappings().one()
            name = step["input"]["function"]["name"]
            pin = t["policy"].get("capabilities", {}).get(name)
            if not pin:
                raise ReleaseDenied()
            try:
                version, s, source = self.service.authorize(c, t, name)
                if (
                    version["id"] != j["release_id"]
                    or s.image_digest != image
                    or digest(j["arguments"]) != j["input_sha256"]
                    or not matches(s.manifest["input_schema"], j["arguments"])
                    or step["status"] != "STARTED"
                    or t["deadline"] <= now
                    or j["attempts"] >= min(3, t["limits"]["max_retries"] + 1)
                ):
                    raise ReleaseDenied()
            except ReleaseDenied:
                result = self._error(pin, "release_unavailable")
                c.execute(
                    update(release_invocations)
                    .where(release_invocations.c.id == j["id"])
                    .values(
                        state="COMPLETED",
                        result=result,
                        result_sha256=digest(result),
                        lease_token=None,
                        lease_until=None,
                        executor_role=role(c),
                    )
                )
                return None
            token = str(uuid4())
            c.execute(
                update(release_invocations)
                .where(release_invocations.c.id == j["id"])
                .values(
                    state="RUNNING",
                    attempts=j["attempts"] + 1,
                    executor_role=role(c),
                    lease_token=token,
                    lease_until=min(now + 15, t["deadline"]),
                )
            )
            return dict(j) | {
                "lease_token": token,
                "image": image,
                "name": name,
                "source_files": source,
                "binding": {"source_sha256": s.source_sha256},
                "oracle_entrypoint": s.manifest["entrypoint"],
                "oracle_inputs": [j["arguments"]],
                "manifest": s.manifest,
            }

    def _owned(self, c, job):
        j = (
            c.execute(
                select(release_invocations)
                .where(release_invocations.c.id == job["id"])
                .with_for_update()
            )
            .mappings()
            .first()
        )
        if not j:
            raise ReleaseDenied()
        self.service.executor(c, j["tenant"])
        t = c.execute(select(tasks).where(tasks.c.id == j["task_id"])).mappings().one()
        if (
            j["state"] != "RUNNING"
            or j["lease_token"] != job["lease_token"]
            or j["executor_role"] != role(c)
            or j["lease_until"] <= self.store.now(c)
            or t["state"] != "RUNNING"
            or t["deadline"] <= self.store.now(c)
        ):
            raise ReleaseDenied()
        v, s, _ = self.service.authorize(c, t, job["name"])
        if v["id"] != j["release_id"] or s.image_digest != job["image"]:
            raise ReleaseDenied()
        return j, t, s

    def heartbeat(self, job):
        try:
            with self.store.engine.begin() as c:
                j, t, _ = self._owned(c, job)
                c.execute(
                    update(release_invocations)
                    .where(release_invocations.c.id == j["id"])
                    .values(lease_until=min(self.store.now(c) + 15, t["deadline"]))
                )
            return True
        except ReleaseDenied:
            return False

    def finish(self, job, result):
        try:
            with self.store.engine.begin() as c:
                j, _t, s = self._owned(c, job)
                values = result.data.get("values") if result.ok else None
                code = None
                if result.ok and (
                    not isinstance(values, list)
                    or len(values) != 1
                    or not matches(s.manifest["output_schema"], values[0])
                ):
                    code = "output_schema_failed"
                elif not result.ok:
                    code = (
                        "platform_secret_denied"
                        if result.error == "platform_secret_denied"
                        else "execution_failed"
                    )
                receipt = InvocationResult(
                    ok=code is None,
                    release_ref=j["release_id"],
                    version=s.version,
                    source_sha256=s.source_sha256,
                    value=values[0] if code is None else None,
                    error=code,
                ).model_dump()
                c.execute(
                    update(release_invocations)
                    .where(release_invocations.c.id == j["id"])
                    .values(
                        state="COMPLETED",
                        result=receipt,
                        result_sha256=digest(receipt),
                        lease_token=None,
                        lease_until=None,
                    )
                )
                if (
                    code
                    and not c.execute(
                        select(release_revocations).where(
                            release_revocations.c.release_id == j["release_id"]
                        )
                    ).first()
                ):
                    c.execute(
                        insert(release_revocations).values(
                            release_id=j["release_id"],
                            operator_role=role(c),
                            reason=code,
                            invocation_id=j["id"],
                            created_at=self.store.now(c),
                        )
                    )
        except ReleaseDenied as exc:
            raise LostLease() from exc
