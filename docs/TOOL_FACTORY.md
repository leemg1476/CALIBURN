# Autonomous Tool/MCP Factory — critical product differentiator

## Objective

An agent should not rewrite fragile ad-hoc scripts every time a recurring business task arises. It should be able to **invent a candidate capability**, subject it to independent verification, and reuse the **version-pinned verified artifact** with reproducible tests and observability.

## Lifecycle

`DISCOVER_GAP → SPECIFY → GENERATE → QUARANTINE → VERIFY → REVIEW → SIGN → REGISTER → STAGE → ACTIVE → OBSERVE → DEPRECATE/QUARANTINE`.

Each transition must be a server-recorded policy decision. Only governance/verification services may transition a candidate into active status; a model-originated tool call is never equivalent to independent approval.

### 1. Discover

Resolver searches existing Tool/MCP/Skill registry by semantic contract, input/output type, permissions, data residency and measured success. Avoid regeneration if a proven equivalent exists. The proposal records the reason existing capabilities failed to match.

### 2. Specify

Agent produces typed input/output schema, normal/edge/error behavior, scope and capability needs, network/file paths, secret scopes, resource ceilings, dependency versions and test cases. A syntactically valid manifest is not proof of acceptable permission scope.

### 3. Generate

Output is a **candidate bundle** (source, `manifest.json`, fixture data, tests, dependency lockfile, rationale). Candidate lives in a quarantine artifact store, has a hash, and is never imported into the platform process.

### 4. Qualify

Independent runner enforces boundaries and executes:

- Contract/schema tests, negative/invalid-input tests, timeout and resource exhaustion tests.
- Regression tests against at least one previously validated invocation where applicable.
- Static analysis, secret and dependency scanners, license/SBOM and provenance checks.
- Injection/poison tests for model-visible tool descriptions and external outputs.
- Replay against recording/fake endpoints, never real production credentials during qualification.
- Manual or stronger independent review for data modification, payment, deployment, external sharing or broad privileges.

### 5. Activate

Activation requires approved signed digest and per-tenant allowlisting; record tool version, reviewer, policy version, test report digest, sandbox image digest and activation timestamp. Do not allow mutable `latest` dependency references in a running task.

### 6. Measure and regress

Per tool-version: invocation count, valid-input rate, observed contract pass rate, error frequency, latency, cost, policy denials, upstream API drift, credential failures and rollback count. Scheduled fixture regression + drift triggers disable/quarantine. Reuse is justified with measured repeatability, not merely tool existence.

## Example scenario

A coding task repeatedly needs to compare GitLab CI templates. If no matching tool exists, agent proposes `gitlab.compare_ci_templates@0.1.0`, generates an MCP server and contract tests, then qualification uses a fake GitLab API. A reviewer approves limited `read_repository` scope. After signing, another task can invoke the pinned version. If GitLab changes response shape, validation fails and the system quarantines only the affected version.

## Invariants

- Candidate and published namespaces are separate.
- Code signing binds **source+dependencies+manifest+tests**, not just the name.
- Tool identity and authentication are not interchangeable. Vault leases are bound to the signed tool digest.
- No self-approval, no unsandboxed generated code, no automatic escalation of network/file/secret permissions.
- Rollbacks preserve prior versions and historical evidence.

## Implemented proposal increment (schema0005)

Exact curated/candidate lookup and immutable typed proposals now have actual durable-worker consumers and authenticated inspection. Source/tests/contracts/fixtures/dependency/SBOM/license declarations remain quarantined inert data. Same-Step crash recovery and unrelated-task reference lookup are tested with real PostgreSQL and scripted models. Semantic gap/equivalence, independent qualification, signing, activation, qualified invocation reuse and drift scoring remain unbuilt. See [proposal runbook](CAPABILITY_PROPOSALS.md), [ADR0010](adr/0010-quarantined-capability-proposals.md) and DEV_PROGRESS.md for exact evidence and rollback. Existing repository test approvals do not authorize Factory source execution.

## Independent static triage increment (schema0006)

The proposal path now has a separate-role/process static triage queue and immutable reports actually consumed by runtime tasks. It only parses bounded inert source/metadata and records incomplete findings; successful processing is never PASS, execution, signing or activation. Explicit separate server grant and independent verifier mapping are required. Full executable qualification/approval/active registry remain open; see FACTORY_STATIC_CHECKS.md and ADR0011.

## Independently reviewed sandbox execution subset (0007)

Default-off capability_request_execution/capability_execute_tests now consume operator-reviewed stdlib tool plans through separate reviewer and host executor roles. Current static reports alone cannot authorize execution; approvals bind exact bundle/report/source/plan/image/implementation/limits. Actual container exit/fixture/extra-test/time/output/stop and worker-crash-reuse evidence exists. Candidates remain QUARANTINED, security/license incomplete, production_approved=false. Full qualification, malicious test/subject anti-tamper, MCP/Skill/nonstdlib adapters, signing/activation and measured qualified invocation reuse remain open. See FACTORY_EXECUTION.md/ADR0012.


## Independently signed evidence subset (0008)

Real Ed25519 signatures now bind complete immutable candidate/static/independent-review/execution/test-plan evidence. Distinct signer role/process and public-key trust mappings, export/import/offline verification, live revocation and API/unrelated-task lookup consumers are implemented. This supersedes the earlier unbuilt-signing statement for evidence integrity only. EVIDENCE_ONLY artifacts remain QUARANTINED/noninvokable/nonactivatable; full qualification, production signing custody/release approval and active registry remain open. See SIGNED_EVIDENCE.md/ADR0013.


## Host-owned finite-vector comparison

Approved unittest child exit0 no longer suffices for a new Factory PASSED receipt/signature. Host-controlled typed vector comparisons run against fresh isolated source/entrypoint/input containers, with expectations outside the subject and complete hash/count/source/subset-plan proof. Actual child reporting attacks are rejected by real PG/Docker tests. Defaults remain candidate-declared; operator vectors have separate provenance. This is an implemented anti-report-tamper subset, not complete property/SAST/poison/dependency/license qualification or executable registry admission. See HOST_ORACLE.md/ADR0014.
