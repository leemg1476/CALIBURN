# Quarantined capability proposals — implemented subset

`capability_lookup(name)` checks exact curated static names, otherwise returns at most20 same-principal/tenant candidate references. Candidates are QUARANTINED, untrusted and noninvokable. A lookup miss is not semantic gap/equivalence classification. The model records a rationale; proposal quality is not measured.

`capability_propose(gap,bundle)` persists manifest, source, tests, fixtures, requested permissions, declared license and agreeing exact dependency/SBOM declarations. Tool/MCP artifacts require a Python source/symbol entrypoint; skills require Markdown. These are candidate shapes, not functioning MCP servers or applied skill instructions. Dependencies are not installed or audited.

Input/output contracts use bounded closed objects, arrays, explicit primitive types, required properties and finite bounds. Refs, external schema resolution and executable validators are rejected. Fixtures match declared input/expected-output shapes without evaluating behavior. Artifact limit32KiB; worker argument limit16KiB takes precedence. Existing safe relative Bundle path/file/byte limits apply; source/test paths cannot overlap. Known configured API/provider/database-password values are denied before persistence, not a universal DLP/Vault guarantee.

Typed output distinguishes curated lookup, candidate lookup, reference and version conflict. Checks report execution NOT_RUN, security NOT_VERIFIED and dependency/license DECLARED_UNVERIFIED. Python syntax VALID only means parseable. Invalid syntax may remain an inert candidate. Stored generated tests never count as passing execution evidence.

Development setup:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
$env:CALIBURN_ALLOW_CAPABILITY_PROPOSALS='true'
# Start the configured existing API and separate runtime worker.
```

Default is false. Clients cannot submit this flag, actor, tenant or policy. New tasks pin the factory digest; ordinary time/model/tool/token/cost/retry limits apply. Successful proposals emit hash/reference-only CAPABILITY_QUARANTINED events. Source stays inert in factory storage and the originating checkpoint, not event payloads. Same-Step recovery returns one receipt/event; another task may reference identical bytes/name/version. Different bytes at the same version return version_conflict.

`GET /api/v1/capabilities/{id}` requires the existing bearer, scopes by server identity and returns untrusted bundle/provenance. There is no invocation/approval/activation endpoint. Model lookup returns metadata/references, not arbitrary candidate source instructions.

Tests use real SQLite/PostgreSQL, runtime worker and API stack with scripted model responses and synthetic identity. A child process dies after proposal commit but before tool checkpoint, then a replacement worker recovers. This proves persistence/recovery, not model intelligence or generated-tool correctness. Git-image licensing approval is still pending and separate.

See ADR0010 for migration/rollback. Independent qualification, signing, promotion, active registry, version-pinned invocation and drift regression remain unbuilt. No new dependency, paid model call, generated execution, external write or Open WebUI modification occurs.

## Follow-on static reports

Schema0006 now implements independent inert static triage via capability_check, a separate server grant, verifier role/process and immutable report API. This supersedes the earlier absence of all independent evidence, but does not implement generated execution, complete security/dependency/license qualification, signing or activation. Proposal-local checks are never overwritten. See FACTORY_STATIC_CHECKS.md/ADR0011.

Schema0007/ADR0012 adds a separate opt-in independently reviewed stdlib sandbox-test consumer. Proposals still execute nothing and remain QUARANTINED; approval/plan/image/identity checks are separate from candidate creation and static findings. See FACTORY_EXECUTION.md; production activation/signing remain unbuilt.
