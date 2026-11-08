# Independent Factory static triage

Implemented path: runtime `capability_check(bundle_ref)` → persisted request → independently configured verifier process → immutable static report → original runtime tool checkpoint. Candidate references must match the server Task's actor/tenant. The request cannot grant source execution or production activation.

Default CALIBURN_ALLOW_CAPABILITY_CHECKS=false is separate from the proposal flag. Set true only on the configured API for NEW development tasks. Worker definitions advertise only each task's actual tool allowlist. Clients cannot submit identity, authority or the server flag. Existing factory task policies are digest-pinned and fail closed after incompatible implementation changes; drain/cancel old granted work during upgrade.

An operator first provisions a separate database role/credential outside the agent. It must not have runtime Task/candidate writes and must differ from author roles. On an operator-owned connection, use the CLI below to map that EXISTING role. The ordinary API/worker connection cannot configure roles or publish reports. Never use an admin DSN for the runtime/verifier or put passwords in command arguments/source/model input.

```powershell
# CALIBURN_DATABASE_URL here names the operator connection, configured outside the agent.
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m caliburn.tool_factory.verifier --configure-role factory_static_verifier --principal independent-static-service --tenant development
# Start a separate process with ONLY the provisioned verifier connection in its environment:
.venv/Scripts/python.exe -m caliburn.tool_factory.verifier
# Or process one available request:
.venv/Scripts/python.exe -m caliburn.tool_factory.verifier --once
# Operator-owned connection: disable mapping, invalidating new/in-flight publications:
.venv/Scripts/python.exe -m caliburn.tool_factory.verifier --disable-role factory_static_verifier
```

These are deployment instructions, not evidence that a production role was provisioned. Actual tests provision temporary synthetic NOLOGIN roles in disposable PostgreSQL, select them through an isolated fixture connection and launch the real verifier module in another OS process. No persistent operator/verifier role or daemon is installed by this milestone.

The report binds canonical bundle SHA256, checker implementation SHA256 and report SHA256; the database stamps the actual verifier role. `GET /api/v1/capabilities/reports/{report_id}` authenticates/scopes inspection. Missing/cross-scope reports404, unauthenticated401; no approval route exists. Model output includes bounded findings with code/path/line, not raw source/secret values. Paths matching known configured secret values are redacted. This is not general secret detection. The source remains QUARANTINED, and proposal checks remain unchanged.

Static findings cover invalid syntax, selected sensitive imports, dynamic/IO calls, dunder introspection and limited English instruction-override patterns. Permission/dependency declarations are flagged for review. Obfuscation, aliases, Korean/other injection text, complete call/data-flow semantics, vulnerabilities and license validity are not comprehensively checked. No dependencies are fetched/installed. No generated test runs and fixture output values are not compared against actual behavior.

Reports can only be BLOCKED or REVIEW_REQUIRED, with source_executed=false, execution=NOT_RUN, security=INCOMPLETE, dependencies=UNVERIFIED, license=UNREVIEWED and activation_eligible=false. Successful queue processing does not mean successful qualification. Independent execution approval, sandbox behavior/property/replay/resource tests, complete SAST/dependency/license audit, signing and activation remain open. Existing repository test approvals cannot authorize Factory bundles.

Queue limits: per-Step request, immutable task/bundle/checker scope, original Task deadline/call timeout, max3 verifier claims, fenced15-second default leases, bounded32KiB bundle,128 findings and fixed5-second analysis-await ceiling. Pure bounded AST work may finish in its thread after cancellation; it cannot execute candidate code or publish without current authority/lease/task state. No hard process/container memory isolation is claimed for parsing. Paused requests do not starve runnable ones; resumed runtime work reuses receipts/reports. Terminal jobs cannot be restarted by queue writes; retries after report commit do not repeat analysis.

Migration0006 is additive; prefer rollback retaining evidence. Explicit backed-up `alembic downgrade 0005_factory` deletes only Factory triage jobs/reports/verifier mappings and requires operator approval. Stop/drain granted tasks first. No existing deployment database was automatically migrated. See ADR0011 and DEV_PROGRESS.md for actual test commands/evidence.

## Follow-on execution gate

ADR0012/schema0007 supplies a separate independently reviewed stdlib tool sandbox-test path. It does not turn static reports into execution/production grants: BLOCKED candidates remain denied and REVIEW_REQUIRED needs an operator plan plus an independent execution decision. Broader property/replay/SAST/dependency/license/anti-tamper qualification and registry activation remain open. Stored authority trigger functions now use trusted-schema lookup with pg_temp last, preventing demonstrated temp-map poisoning. See FACTORY_EXECUTION.md.
