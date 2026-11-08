"""Transactional candidate creation. This module never imports candidate source."""

import ast
from uuid import uuid4

from sqlalchemy import insert, select, text
from sqlalchemy.exc import IntegrityError

from caliburn.runtime.redaction import contains_secret
from caliburn.runtime.schema import steps
from caliburn.runtime.store import NotFound
from caliburn.tool_factory.contracts import (
    FACTORY_DIGEST,
    INPUTS,
    CandidateLookup,
    CandidateView,
    CuratedLookup,
    Proposal,
    VersionConflict,
    digest,
    tool_contracts,
)
from caliburn.tool_factory.execution_contracts import EXEC_MANIFESTS
from caliburn.tool_factory.schema import bundles, proposals
from caliburn.tools import TOOL_CONTRACTS


class FactoryDenied(Exception):
    pass


class Factory:
    def __init__(self, store, secrets=()):
        self.store, self.secrets = store, secrets

    def lookup(self, task_id, token, name):
        with self.store.engine.begin() as c:
            task = self._authorized(c, task_id, token, "capability_lookup")
            catalog = TOOL_CONTRACTS | tool_contracts() | EXEC_MANIFESTS
            if name in catalog:
                return {
                    "name": name,
                    "state": "ACTIVE_CURATED",
                    "can_invoke": name in task["policy"]["tools"],
                    "contract": catalog[name],
                }
            rows = c.execute(
                select(bundles)
                .where(
                    bundles.c.actor == task["actor"],
                    bundles.c.tenant == task["tenant"],
                    bundles.c.name == name,
                )
                .order_by(bundles.c.created_at.desc(), bundles.c.id)
                .limit(20)
            ).mappings()
            from caliburn.tool_factory.registry import ArtifactRegistry

            registry = ArtifactRegistry(self.store, secrets=self.secrets)
            return {
                "name": name,
                "can_invoke": False,
                "candidates": [
                    self._view(r)
                    | {
                        "signed_artifacts": registry.summaries(
                            c, r["id"], task["actor"], task["tenant"]
                        )
                    }
                    for r in rows
                ],
            }

    def _authorized(self, c, task_id, token, tool):
        task = self.store._owned(c, task_id, token)
        if (
            task["deadline"] <= self.store.now(c)
            or tool not in task["policy"]["tools"]
            or task["policy"].get("factory_digest") != FACTORY_DIGEST
        ):
            raise FactoryDenied()
        return task

    @staticmethod
    def _view(row):
        return {
            key: row[key]
            for key in ("id", "name", "version", "kind", "state", "sha256", "checks", "created_at")
        } | {"can_invoke": False, "untrusted": True}

    def read(self, bundle_id, actor="development-service", tenant="development"):
        with self.store.engine.connect() as c:
            row = (
                c.execute(
                    select(bundles).where(
                        bundles.c.id == bundle_id,
                        bundles.c.actor == actor,
                        bundles.c.tenant == tenant,
                    )
                )
                .mappings()
                .first()
            )
            if row is None:
                raise NotFound()
            result = self._view(row) | {
                "bundle": row["payload"],
                "origin_task_id": row["origin_task_id"],
                "origin_step_id": row["origin_step_id"],
                "creator_role": row["creator_role"],
            }
            if contains_secret(result, self.secrets):
                raise FactoryDenied()
            return result

    def propose(self, task_id, token, step_id, proposal: Proposal):
        payload = proposal.bundle.model_dump()
        if contains_secret(proposal.model_dump(), self.secrets):
            raise FactoryDenied()
        if (
            proposal.bundle.manifest.name.startswith("capability_")
            or proposal.bundle.manifest.name in set(TOOL_CONTRACTS) | set(INPUTS)
            or proposal.bundle.manifest.name.startswith("repo_")
        ):
            raise FactoryDenied()
        sha, request_sha = digest(payload), digest(proposal.model_dump())
        checks = {
            "contract_fixtures": "VALID",
            "python_syntax": "VALID",
            "execution": "NOT_RUN",
            "security": "NOT_VERIFIED",
            "license": "DECLARED_UNVERIFIED",
            "dependencies": "DECLARED_UNVERIFIED",
        }
        for path, source in (payload["sources"] | payload["tests"]).items():
            if path.endswith(".py"):
                try:
                    ast.parse(source)
                except (SyntaxError, ValueError, RecursionError):
                    checks["python_syntax"] = "INVALID"
        with self.store.engine.begin() as c:
            task = self._authorized(c, task_id, token, "capability_propose")
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
            if not step or step["input"].get("function", {}).get("name") != "capability_propose":
                raise FactoryDenied()
            try:
                recorded = Proposal.model_validate_json(step["input"]["function"]["arguments"])
            except (KeyError, ValueError) as exc:
                raise FactoryDenied() from exc
            if digest(recorded.model_dump()) != request_sha:
                raise FactoryDenied()
            prior = (
                c.execute(select(proposals).where(proposals.c.step_id == step_id))
                .mappings()
                .first()
            )
            if prior:
                if prior["request_sha256"] != request_sha:
                    raise FactoryDenied()
                row = (
                    c.execute(select(bundles).where(bundles.c.id == prior["bundle_id"]))
                    .mappings()
                    .one()
                )
                return self._view(row)
            manifest = proposal.bundle.manifest
            query = select(bundles).where(
                bundles.c.actor == task["actor"],
                bundles.c.tenant == task["tenant"],
                bundles.c.name == manifest.name,
                bundles.c.version == manifest.version,
            )
            row = c.execute(query).mappings().first()
            if row is None:
                role = (
                    c.scalar(text("SELECT current_user"))
                    if c.dialect.name == "postgresql"
                    else "sqlite-test-only"
                )
                values = {
                    "id": str(uuid4()),
                    "origin_task_id": task_id,
                    "origin_step_id": step_id,
                    "actor": task["actor"],
                    "tenant": task["tenant"],
                    "creator_role": role,
                    "name": manifest.name,
                    "version": manifest.version,
                    "kind": manifest.kind,
                    "state": "QUARANTINED",
                    "sha256": sha,
                    "payload": payload,
                    "checks": checks,
                    "created_at": self.store.now(c),
                }
                try:
                    with c.begin_nested():
                        c.execute(insert(bundles).values(**values))
                    row = values
                except IntegrityError:
                    row = c.execute(query).mappings().first()
                    if row is None:
                        raise
            if row["sha256"] != sha:
                return {"ok": False, "error": "version_conflict", "can_invoke": False}
            c.execute(
                insert(proposals).values(
                    step_id=step_id,
                    task_id=task_id,
                    bundle_id=row["id"],
                    actor=task["actor"],
                    tenant=task["tenant"],
                    gap=proposal.gap,
                    request_sha256=request_sha,
                    created_at=self.store.now(c),
                )
            )
            self.store._event(
                c,
                task,
                "CAPABILITY_QUARANTINED",
                {"bundle_id": row["id"], "sha256": sha, "step_id": step_id},
            )
            self.store._save(c, task)
            return self._view(row)

    def invoke(self, task_id, token, step_id, name, arguments):
        if name == "capability_check":
            raise FactoryDenied()
        value = INPUTS[name].model_validate_json(arguments)
        if name == "capability_lookup":
            result = self.lookup(task_id, token, value.name)
            model = CuratedLookup if result.get("state") == "ACTIVE_CURATED" else CandidateLookup
        else:
            result = self.propose(task_id, token, step_id, value)
            model = VersionConflict if result.get("error") == "version_conflict" else CandidateView
        return model.model_validate(result).model_dump()
