"""Independent internal release, immutable versions, live trust and head selection."""

import re
from uuid import uuid4

from sqlalchemy import case, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from caliburn.tool_factory.artifact_integrity import ArtifactDenied, key_id
from caliburn.tool_factory.checks import VerifierAuthority, mutable_runtime, role
from caliburn.tool_factory.contracts import CHECKER_DIGEST, digest
from caliburn.tool_factory.oracle import read_plan, require_proof
from caliburn.tool_factory.registry import ArtifactRegistry
from caliburn.tool_factory.release_contracts import (
    ReleaseDenied,
    ReleaseStatement,
    profile,
    release_digest,
    release_sign,
    release_verify,
)
from caliburn.tool_factory.schema import (
    release_decisions,
    release_executors,
    release_heads,
    release_invocations,
    release_requests,
    release_reviewers,
    release_revocations,
    release_versions,
    signed_artifacts,
)


class ReleaseService:
    def __init__(self, store, *, secrets=()):
        self.store, self.secrets = store, secrets
        self.artifacts = ArtifactRegistry(store, secrets=secrets)

    def configure(self, name, principal, kind, tenant="development"):
        if (
            not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", name)
            or not 1 <= len(principal) <= 80
            or kind not in {"REVIEWER", "EXECUTOR", "SIGNER"}
        ):
            raise ReleaseDenied()
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            if mutable_runtime(c, name):
                raise ReleaseDenied()
            schema = c.scalar(text("SELECT current_schema()")).replace('"', '""')
            c.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{name}"'))
            for table in self.store.engine.dialect.get_table_names(
                c, schema=c.scalar(text("SELECT current_schema()"))
            ):
                if table.startswith(("registry_", "factory_", "runtime_")):
                    c.execute(text(f'GRANT SELECT ON "{schema}"."{table}" TO "{name}"'))
            if kind in {"REVIEWER", "EXECUTOR"}:
                table = release_reviewers if kind == "REVIEWER" else release_executors
                old = c.execute(select(table).where(table.c.db_role == name)).mappings().first()
                values = {
                    "db_role": name,
                    "principal": principal,
                    "tenant": tenant,
                    "enabled": "yes",
                }
                if old and dict(old) != values:
                    raise ReleaseDenied()
                if not old:
                    c.execute(insert(table).values(**values))
            else:
                who = c.execute(
                    text(
                        "SELECT 1 FROM factory_registry_roles WHERE db_role=:r AND tenant=:t AND enabled='yes'"
                    ),
                    {"r": name, "t": tenant},
                ).first()
                if not who:
                    raise ReleaseDenied()
            grants = {
                "REVIEWER": ["INSERT ON registry_decisions"],
                "EXECUTOR": [
                    "UPDATE (state,attempts,lease_token,lease_until,executor_role,result,result_sha256) ON registry_invocations",
                    "INSERT ON registry_revocations",
                ],
                "SIGNER": [
                    "INSERT ON registry_versions",
                    "INSERT,UPDATE ON registry_heads",
                    "INSERT ON registry_head_events",
                ],
            }[kind]
            for grant in grants:
                c.execute(text("GRANT " + grant + f' TO "{name}"'))

    def disable(self, name, kind):
        table = release_reviewers if kind == "REVIEWER" else release_executors
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            c.execute(update(table).where(table.c.db_role == name).values(enabled="no"))

    def executor(self, c, tenant):
        who = (
            c.execute(
                select(release_executors).where(
                    release_executors.c.db_role == role(c),
                    release_executors.c.tenant == tenant,
                    release_executors.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        if not who or mutable_runtime(c, role(c)):
            raise ReleaseDenied()
        return who

    def _artifact(self, c, artifact_id):
        row = (
            c.execute(select(signed_artifacts).where(signed_artifacts.c.id == artifact_id))
            .mappings()
            .first()
        )
        if not row:
            raise ReleaseDenied()
        envelope = self.artifacts._verify(c, row)
        s = envelope.statement
        require_proof(s.execution_binding, s.execution_result.isolation, current=True)
        p = read_plan(s.plan_files)
        if (
            p.case_source != "operator"
            or len({digest(x.input) for x in p.cases}) < 2
            or s.static_report.checker_sha256 != CHECKER_DIGEST
        ):
            raise ReleaseDenied()
        qualification = profile(s.bundle.model_dump())
        return row, s, qualification

    def _binding(self, c, artifact_id):
        row, s, q = self._artifact(c, artifact_id)
        return {
            "format": "internal-release-request-v1",
            "scope": "internal_development",
            "artifact_ref": row["id"],
            "artifact_sha256": row["sha256"],
            "actor": row["actor"],
            "tenant": row["tenant"],
            "name": s.bundle.manifest.name,
            "version": s.bundle.manifest.version,
            "image_digest": s.execution_binding["image_digest"],
            "source_sha256": q["source_sha256"],
            "qualification": q,
            "manifest": s.bundle.manifest.model_dump(),
            "release_policy_sha256": release_digest(),
        }

    def request(self, artifact_id, ttl=3600):
        if type(ttl) is not int or not 1 <= ttl <= 3600:
            raise ReleaseDenied()
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            binding = self._binding(c, artifact_id)
            now = self.store.now(c)
            rid = str(uuid4())
            c.execute(
                insert(release_requests).values(
                    id=rid,
                    artifact_id=artifact_id,
                    actor=binding["actor"],
                    tenant=binding["tenant"],
                    binding=binding,
                    sha256=digest(binding),
                    creator_role=role(c),
                    created_at=now,
                    expires_at=now + ttl,
                )
            )
            return rid

    def inspect(self, request_id):
        with self.store.engine.connect() as c:
            row = (
                c.execute(select(release_requests).where(release_requests.c.id == request_id))
                .mappings()
                .first()
            )
            if not row:
                raise ReleaseDenied()
            return dict(row)

    def decide(self, request_id, sha, decision, *, internal_license_approved=False):
        if decision not in {"APPROVE", "REJECT"} or (
            decision == "APPROVE" and not internal_license_approved
        ):
            raise ReleaseDenied()
        with self.store.engine.begin() as c:
            r = (
                c.execute(select(release_requests).where(release_requests.c.id == request_id))
                .mappings()
                .first()
            )
            if (
                not r
                or r["sha256"] != sha
                or r["expires_at"] <= self.store.now(c)
                or r["binding"] != self._binding(c, r["artifact_id"])
            ):
                raise ReleaseDenied()
            who = (
                c.execute(
                    select(release_reviewers).where(
                        release_reviewers.c.db_role == role(c),
                        release_reviewers.c.tenant == r["tenant"],
                        release_reviewers.c.enabled == "yes",
                    )
                )
                .mappings()
                .first()
            )
            ar, s, _ = self._artifact(c, r["artifact_id"])
            _, authors = self.artifacts.snapshot(c, s.execution_job_ref)
            authors.discard(
                s.decision["reviewer_role"]
            )  # independent human may approve distinct purposes
            authors |= {r["creator_role"], ar["signer_role"]}
            if (
                not who
                or role(c) in authors
                or who["principal"] == r["actor"]
                or mutable_runtime(c, role(c))
            ):
                raise ReleaseDenied()
            old = (
                c.execute(
                    select(release_decisions).where(release_decisions.c.request_id == request_id)
                )
                .mappings()
                .first()
            )
            if old:
                if old["decision"] != decision or old["reviewer_role"] != role(c):
                    raise ReleaseDenied()
                return old["id"]
            did = str(uuid4())
            c.execute(
                insert(release_decisions).values(
                    id=did,
                    request_id=request_id,
                    reviewer_role=role(c),
                    decision=decision,
                    binding_sha256=sha,
                    license_scope="internal_development"
                    if internal_license_approved
                    else "not_approved",
                    created_at=self.store.now(c),
                    expires_at=r["expires_at"],
                )
            )
            return did

    def _approved(self, c, request_id):
        r = (
            c.execute(select(release_requests).where(release_requests.c.id == request_id))
            .mappings()
            .first()
        )
        d = (
            c.execute(select(release_decisions).where(release_decisions.c.request_id == request_id))
            .mappings()
            .first()
        )
        if (
            not r
            or not d
            or d["decision"] != "APPROVE"
            or d["license_scope"] != "internal_development"
            or d["binding_sha256"] != r["sha256"]
        ):
            raise ReleaseDenied()
        who = (
            c.execute(
                select(release_reviewers).where(
                    release_reviewers.c.db_role == d["reviewer_role"],
                    release_reviewers.c.tenant == r["tenant"],
                    release_reviewers.c.enabled == "yes",
                )
            )
            .mappings()
            .first()
        )
        if (
            not who
            or mutable_runtime(c, d["reviewer_role"])
            or min(r["expires_at"], d["expires_at"]) <= self.store.now(c)
        ):
            raise ReleaseDenied()
        if digest(r["binding"]) != r["sha256"] or r["binding"] != self._binding(
            c, r["artifact_id"]
        ):
            raise ReleaseDenied()
        return r, d, who

    def activate(self, request_id, private):
        fingerprint = key_id(private.public_key().public_bytes_raw())
        with self.store.engine.begin() as c:
            r, d, reviewer = self._approved(c, request_id)
            key, _, who = self.artifacts._key(c, fingerprint, r["tenant"], signer=role(c))
            if (
                role(c) == d["reviewer_role"]
                or who["principal"] == reviewer["principal"]
                or who["principal"] == r["actor"]
            ):
                raise ReleaseDenied()
            old = (
                c.execute(
                    select(release_versions).where(release_versions.c.request_id == request_id)
                )
                .mappings()
                .first()
            )
            if old:
                self._verify(c, old, r["actor"], r["tenant"])
                return old["id"]
            b = r["binding"]
            now = int(self.store.now(c))
            vid = str(uuid4())
            s = ReleaseStatement(
                request_ref=request_id,
                binding_sha256=r["sha256"],
                approval_ref=d["id"],
                approval_sha256=digest(dict(d)),
                artifact_ref=r["artifact_id"],
                artifact_sha256=b["artifact_sha256"],
                actor=r["actor"],
                tenant=r["tenant"],
                name=b["name"],
                version=b["version"],
                image_digest=b["image_digest"],
                source_sha256=b["source_sha256"],
                qualification=b["qualification"],
                manifest=b["manifest"],
                key_id=fingerprint,
                issued_at=now,
                expires_at=int(min(key["expires_at"], r["expires_at"])),
            )
            envelope = release_sign(s, private)
            c.execute(
                insert(release_versions).values(
                    id=vid,
                    request_id=request_id,
                    artifact_id=r["artifact_id"],
                    actor=s.actor,
                    tenant=s.tenant,
                    name=s.name,
                    version=s.version,
                    signer_role=role(c),
                    key_id=fingerprint,
                    envelope=envelope,
                    sha256=digest(envelope),
                    created_at=self.store.now(c),
                    expires_at=s.expires_at,
                )
            )
            self._head(c, s.actor, s.tenant, s.name, vid)
            return vid

    def _verify(self, c, row, actor, tenant):
        if (
            row["actor"] != actor
            or row["tenant"] != tenant
            or digest(row["envelope"]) != row["sha256"]
        ):
            raise ReleaseDenied()
        if c.execute(
            select(release_revocations).where(release_revocations.c.release_id == row["id"])
        ).first():
            raise ReleaseDenied()
        _, public, _ = self.artifacts._key(c, row["key_id"], tenant, signer=row["signer_role"])
        s = release_verify(row["envelope"], public, actor, tenant, self.store.now(c))
        r, d, _ = self._approved(c, row["request_id"])
        b = r["binding"]
        expected = {
            "request_ref": r["id"],
            "binding_sha256": r["sha256"],
            "approval_ref": d["id"],
            "approval_sha256": digest(dict(d)),
            "artifact_ref": r["artifact_id"],
            "artifact_sha256": b["artifact_sha256"],
            "actor": actor,
            "tenant": tenant,
            "name": b["name"],
            "version": b["version"],
            "image_digest": b["image_digest"],
            "source_sha256": b["source_sha256"],
            "qualification": b["qualification"],
            "manifest": b["manifest"],
            "key_id": row["key_id"],
        }
        if (
            any(s.model_dump()[k] != v for k, v in expected.items())
            or s.expires_at != row["expires_at"]
        ):
            raise ReleaseDenied()
        return s

    def version(self, c, version_id, actor, tenant):
        row = (
            c.execute(select(release_versions).where(release_versions.c.id == version_id))
            .mappings()
            .first()
        )
        if not row:
            raise ReleaseDenied()
        try:
            return row, self._verify(c, row, actor, tenant)
        except (ArtifactDenied, ValueError, KeyError) as exc:
            raise ReleaseDenied() from exc

    def select(self, c, names, actor, tenant):
        pins = {}
        automatic = names is None
        if automatic:
            names = list(
                c.scalars(
                    select(release_heads.c.name)
                    .where(release_heads.c.actor == actor, release_heads.c.tenant == tenant)
                    .order_by(release_heads.c.name)
                    .limit(64)
                )
            )
        for name in names:
            h = (
                c.execute(
                    select(release_heads).where(
                        release_heads.c.actor == actor,
                        release_heads.c.tenant == tenant,
                        release_heads.c.name == name,
                    )
                )
                .mappings()
                .first()
            )
            if not h:
                raise ReleaseDenied()
            try:
                row, s = self.version(c, h["release_id"], actor, tenant)
            except ReleaseDenied:
                if automatic:
                    continue
                raise
            pins[name] = {
                "release_id": row["id"],
                "envelope_sha256": row["sha256"],
                "manifest": s.manifest,
                "version": s.version,
                "source_sha256": s.source_sha256,
                "image_digest": s.image_digest,
            }
            if len(pins) == 8:
                break
        return pins

    def authorize(self, c, task, name):
        pin = task["policy"].get("capabilities", {}).get(name)
        if (
            not pin
            or task["policy"].get("registry_digest") != release_digest()
            or name not in task["policy"]["tools"]
        ):
            raise ReleaseDenied()
        row, s = self.version(c, pin["release_id"], task["actor"], task["tenant"])
        if row["sha256"] != pin["envelope_sha256"] or s.manifest != pin["manifest"]:
            raise ReleaseDenied()
        artifact = (
            c.execute(select(signed_artifacts).where(signed_artifacts.c.id == s.artifact_ref))
            .mappings()
            .one()
        )
        statement = self.artifacts._verify(c, artifact).statement
        return row, s, statement.bundle.sources

    def _head(self, c, actor, tenant, name, vid):
        stmt = pg_insert(release_heads).values(
            actor=actor,
            tenant=tenant,
            name=name,
            release_id=vid,
            operator_role=role(c),
            updated_at=self.store.now(c),
        )
        c.execute(
            stmt.on_conflict_do_update(
                index_elements=["actor", "tenant", "name"],
                set_={"release_id": vid, "operator_role": role(c), "updated_at": self.store.now(c)},
            )
        )

    def rollback(self, version_id, actor="development-service", tenant="development"):
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            _, s = self.version(c, version_id, actor, tenant)
            self._head(c, actor, tenant, s.name, version_id)

    def revoke(self, version_id, reason="operator_revoked"):
        with self.store.engine.begin() as c:
            VerifierAuthority(self.store)._owner(c)
            row = (
                c.execute(select(release_versions).where(release_versions.c.id == version_id))
                .mappings()
                .first()
            )
            if not row:
                raise ReleaseDenied()
            if not c.execute(
                select(release_revocations).where(release_revocations.c.release_id == version_id)
            ).first():
                c.execute(
                    insert(release_revocations).values(
                        release_id=version_id,
                        operator_role=role(c),
                        reason=reason,
                        created_at=self.store.now(c),
                    )
                )

    def active(self, actor="development-service", tenant="development"):
        with self.store.engine.connect() as c:
            rows = (
                c.execute(
                    select(release_heads).where(
                        release_heads.c.actor == actor, release_heads.c.tenant == tenant
                    )
                )
                .mappings()
                .all()
            )
            result = []
            for h in rows:
                try:
                    row, s = self.version(c, h["release_id"], actor, tenant)
                except ReleaseDenied:
                    continue
                result.append(
                    {
                        "release_ref": row["id"],
                        "name": s.name,
                        "version": s.version,
                        "manifest": s.manifest,
                        "scope": s.scope,
                    }
                )
            return result

    def metrics(self, actor="development-service", tenant="development"):
        with self.store.engine.connect() as c:
            rows = (
                c.execute(
                    select(release_versions)
                    .where(release_versions.c.actor == actor, release_versions.c.tenant == tenant)
                    .order_by(release_versions.c.created_at.desc())
                    .limit(100)
                )
                .mappings()
                .all()
            )
            result = []
            for row in rows:
                counts = c.execute(
                    select(
                        func.count(),
                        func.coalesce(func.sum(release_invocations.c.attempts), 0),
                        func.coalesce(
                            func.sum(
                                case(
                                    (release_invocations.c.result["ok"].as_boolean() == True, 1),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                        func.coalesce(
                            func.sum(
                                case(
                                    (release_invocations.c.result["ok"].as_boolean() == False, 1),
                                    else_=0,
                                )
                            ),
                            0,
                        ),
                    )
                    .select_from(release_invocations)
                    .where(release_invocations.c.release_id == row["id"])
                ).one()
                revoked = (
                    c.execute(
                        select(release_revocations).where(
                            release_revocations.c.release_id == row["id"]
                        )
                    )
                    .mappings()
                    .first()
                )
                result.append(
                    {
                        "release_ref": row["id"],
                        "name": row["name"],
                        "version": row["version"],
                        "invocations": counts[0],
                        "dispatch_attempts": counts[1],
                        "successful": counts[2],
                        "failed": counts[3],
                        "quarantined": bool(revoked),
                        "revocation_reason": revoked["reason"] if revoked else None,
                    }
                )
            return result
