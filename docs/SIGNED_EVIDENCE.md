# Independently signed evidence (schema 0008)

This is an implemented integrity and read-consumer slice, not a production capability registry. The signer consumes an actual completed Factory execution job and its persisted runtime tool checkpoint. The candidate remains QUARANTINED; every envelope has purpose EVIDENCE_ONLY, production_approved=false, and admission can_invoke=false / activation_eligible=false.

## Trust and payload

An owner configures a distinct PostgreSQL signer role and registers only its Ed25519 public key. The signer must have no runtime/candidate mutation authority and must differ from the source/request/plan/static reviewer/execution reviewer/executor authors and task actor. The signing process alone opens an encrypted PKCS8 private-key file using CALIBURN_SIGNING_KEY_PASSWORD. No private key generation/storage, production role provisioning, HSM/KMS or human OIDC workflow is supplied by this increment. Test keys/passwords are ephemeral fixtures, never repository files or model input.

The signature binds the full candidate bundle (source, tests, contract, manifest, dependency/SBOM/license declarations), static report, execution binding/result, exact independent approval, independent test plan files, actor/tenant, signer key/policy hash and validity window. Source/execution/report hashes and successful test outcome must agree. Completed job and consumed tool checkpoint must match; failed, unfinished, revoked, self-authored and cross-scope evidence is denied. Static security/license qualification remains incomplete even when tests pass.

Canonical bytes are Python's sorted-key compact UTF-8 JSON with nonfinite numbers forbidden, prefixed by a versioned CALIBURN/EVIDENCE_ONLY/ED25519 domain separator. This is a project format, not an RFC8785 implementation or cross-language canonicalization claim. Envelopes reject duplicate JSON keys, unexpected algorithm/purpose, inconsistent hashes and payloads over 2 MiB. SHA256 of the raw 32-byte public key identifies the trust root. A packet cannot supply its own trusted key.

Online reads verify the signature, scoped metadata, immutable source/evidence graph, key validity/revocation, enabled signer/verifier/reviewer/executor mappings and current execution revocation. Revocation makes retained evidence untrusted; bytes are not deleted. Offline verification checks signature/scope/time against a separately supplied public key; it cannot establish current server revocation, role status, execution authenticity or release approval. Trust the public key through an independent operator channel.

## Running consumers

Authenticated GET /api/v1/capabilities/artifacts/{id} returns the verified envelope plus denial-only admission, with Cache-Control:no-store. Wrong scope/missing ID returns404; invalid trust returns409. Existing capability_lookup exposes up to5 scoped VERIFIED_EVIDENCE or UNTRUSTED summaries per candidate to unrelated tasks. Neither endpoint offers activation or executable invocation; only existing curated tools remain invokable.

The owner supplies the role/tenant/principal and public PEM through the existing protected control-plane connection; the signer uses its own separate DB connection. Do not use application/admin credentials for signing. Example actions, using operator-provisioned files outside the source tree:

```powershell
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --configure-role factory_signer --principal independent-signer --tenant development
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --register-key C:/secure/signer-public.pem --signer-role factory_signer
# Switch to the separate signer connection, and supply the password through its protected environment.
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --publish-job <completed-job-id> --private-key C:/secure/signer-encrypted.pem
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --export <artifact-id>
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --import-envelope C:/review/evidence.json
# Offline verification needs no database or private key.
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --verify-envelope C:/review/evidence.json --trusted-public-key C:/secure/signer-public.pem --actor development-service --tenant development
# Owner connection only:
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --revoke-key <public-key-sha256>
.venv/Scripts/python.exe -m caliburn.tool_factory.signing_control --disable-role factory_signer
```

CLI diagnostics intentionally omit key/password/DSN/provider exceptions. Role/key mappings are owner controlled. Key bindings are immutable and ACTIVE→REVOKED is irreversible; register a new key for rotation. Disabling mappings is distinct from DB LOGIN/credential offboarding. Direct trusted DB owners can alter a database; this is not compromised-owner isolation. SQL gates provenance/immutability but does not perform Ed25519 verification: consumers must call the public verifier before trusting stored records.

## Migration and rollback

0008_signed_evidence adds factory_registry_roles, factory_signing_keys and factory_signed_artifacts after0007. Public keys only; unique execution-job/key receipts prevent duplicate publication. New trigger lookup paths use the trusted schema with pg_temp last. Runtime has SELECT only, never sign/key-authority writes. No production schema was migrated during development; tests use disposable schemas. The Factory implementation digest changes, so reconcile/drain old pinned work rather than silently repin it.

Prefer compatible code rollback retaining immutable evidence. Stop signers/new requests before rollback. A separately approved backed-up Alembic downgrade to0007 deletes these three tables/public trust records and their two new functions, preserving previous execution/source evidence and0007 shared trigger hardening. No live grants, daemon or production key were created by tests.

## Evidence and limits

tests/test_signed_evidence.py covers pure cryptographic corruption/algorithm/scope/time/purpose tests (explicit synthetic data), then actual PostgreSQL roles plus Docker execution, a separate signer OS process opening an encrypted ephemeral key, export/import replay, public HTTP/unrelated-task lookup, independent offline verification, live key/role/review revocation, self-sign denial, immutable rows and TEMP mapping denial. See docs/evidence/m3-signing-git-focused.xml and DEV_PROGRESS.md for final counts/commands. These tests do not establish complete malicious-subject anti-tamper, supply-chain/security/license qualification, MCP/Skill/dependency execution, production release approval, active version rollout or measured executable reuse. Those remain next milestones.
