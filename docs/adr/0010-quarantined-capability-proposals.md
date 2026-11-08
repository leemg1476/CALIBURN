# ADR 0010 — Durable inert capability proposals

Status: accepted for development proposals; qualification/activation not approved.

The runtime needs a real missing-capability consumer before a production registry. Model source, permission requests, test assertions and license declarations must never become executable authority.

New tasks receive `capability_lookup` and `capability_propose` only with trusted server `CALIBURN_ALLOW_CAPABILITY_PROPOSALS=true` (default false). Policy pins the implementation digest; existing tasks keep their allowlist. Exact-name lookup returns curated static contracts or scoped untrusted candidate references. Semantic equivalence/classification remains unbuilt. Reserved names cannot be shadowed.

Canonical SHA256 binds manifest, bounded closed JSON contracts, source, generated tests, deterministic fixtures, exact declared dependencies, SBOM and declared license. No import, dependency installation, MCP connection, skill adoption, network or candidate execution occurs. Python parsing and fixture shape checks are metadata, not independently verified behavior/safety/license evidence.

Migration0005 adds append-only factory_bundles and factory_proposals. Server actor/tenant, author DB role and originating Task/Step provide provenance. A scoped name/version is immutable. Identical artifacts can be referenced by other tasks; changed artifacts require another version. Step receipts make candidate persistence and task event atomic. Death before the tool checkpoint returns the same receipt on recovery. Savepoints resolve concurrent identical insertions. Live lease/deadline, exact step input and pinned task policy are checked. PostgreSQL scope/immutable triggers and separate runtime-role mutation revocations reinforce the application boundary; DB owners/admins remain trusted.

The sole state is QUARANTINED. No candidate invocation, approval, signing, activation or publication route exists. Requested permissions/grant references confer no authority; candidate names never enter executable definitions. HTTP inspection uses fixed development service identity, not OIDC/customer isolation. Application queries enforce scope; direct DB access is a trusted service boundary, not tenant RLS.

Next slices require an independent runner/evidence path and separate review/signing/activation authority. Existing repository unittest approval does not authorize factory bundles. This is proposal/reference reuse, not qualified capability execution reuse.

Migration is additive from0004 to0005. Disabling the flag prevents new grants; stop/cancel already granted tasks when revoking the feature. Old workers must not process newly granted tasks. Prefer application rollback retaining schema/evidence. After explicit backup/operator approval, `alembic downgrade 0004_candidate_parent` drops only factory tables and their evidence, so it is destructive. No dependency/license/branding change occurs here.
