# Codex implementation milestones

Complete in order. Each milestone requires a demo, durable API contract, negative tests and rollout notes. Do not equate a green unit test with platform completion.

## M0 — Bootstrap spike (included)

- [x] API token authentication for **single-service development only**.
- [x] `/v1/models` and non-streaming `/v1/chat/completions` basic OpenAI compatibility.
- [x] Bounded tool-call loop with typed built-in tools; local/mock and OpenAI-compatible provider adapter.
- [x] Local SQLite task metadata + legal state transitions.
- [x] Unit/API tests, local Docker image and architecture/security/license specs.
- [x] Actual pinned/unmodified Open WebUI browser smoke on target host with fixture inference and matching PostgreSQL task evidence (development loopback transport; not production identity).

## M1 — Durable asynchronous task runtime

- [x] PostgreSQL SQLAlchemy/Alembic schema: Task, Run/lease, Step, append-only Event, result attachment, budget and server-owned actor/policy.
- [x] Idempotent submit, status, pause/cancel/resume and authorized event replay APIs.
- [x] Separate async worker; persisted queue; SKIP LOCKED claim, heartbeat, lease expiry and stale-worker fencing.
- [x] Durable model/tool loop, checkpoint recovery; step/tool/token/cost reservation, retry and wall/call time limits.
- [x] Terminal state rules; WAITING_APPROVAL cannot be resumed by a general worker/client. Narrow independent DB-role candidate review is implemented; enterprise approval/promotion remains M3/M4.
- [x] SSE Last-Event-ID replay/reconnect, real HTTP demo, OpenAI durable model adapter.
- [x] Failure tests: process death after tool execution before commit, duplicate submit/claim, pause/cancel in flight, expiry, reconnect, budget/timeout, tool deny and secret guard.
- [x] Actual Open WebUI browser smoke plus durable OpenAI SSE framing and disconnect recovery.
- [x] Independent task Step/Run/event timeline UI, authenticated history, budgets/results/reviews, pause/cancel/resume and actual browser reconnect/control/XSS checks; enterprise identity and embedded Open WebUI navigation remain open.

Evidence, exact commands, migrations and limitations: [DEV_PROGRESS.md](DEV_PROGRESS.md),
[M1_RUNTIME.md](M1_RUNTIME.md), [ADR 0001](adr/0001-durable-runtime.md).
M1 is a working backend slice, not a claim of safe autonomous repository coding.

## M2 — Secure coding agent vertical slice

- [ ] Git repository checkout and diff in per-task workspace; explicit repo ACL.
- [x] Per-request non-root container for source data operations: read-only root, no Docker socket/host mounts, CPU/memory/PID limits, network none, immutable image/source and independently inspected settings.
- [x] Server-registered immutable snapshots, scope/TTL/revoke and local committed Git-object import with provenance; no model-selected host paths.
- [x] Typed list/read/literal-search/inert-patch tools consumed through a durable queue by the real runtime worker.
- [x] Durable immutable candidate + exact-digest review request, independent PostgreSQL reviewer role, WAITING_APPROVAL, approve/reject/revoke/expiry and worker resume; execution requires a separate opt-in grant and consumer.
- [ ] Qualification for executing untrusted candidate/test code (not enabled by the read/patch runner).
- [x] Independently approved stdlib unittest execution with actual baseline/candidate evidence in separate fresh containers; arbitrary commands/dependencies remain unsupported.
- [x] Plan → code → test → inspect evidence → parent-based repair loop with cumulative model/token/tool/time budgets; actual PostgreSQL/Docker fixture evidence, real-model quality benchmark pending.
- [ ] Policy approval for PR creation and all write-side effects; rollback option.
- [ ] Benchmark on fixed small real repositories: success evidence and failure taxonomy, not model self-scores.

## M3 — Capability factory and governed registry

- [x] M3.1a: Exact curated/candidate lookup and typed immutable quarantined proposals consumed by durable workers; unrelated-task inspection, conflict/replay/scope/deny tests. See CAPABILITY_PROPOSALS.md/ADR0010.
- [ ] M3.1b: Semantic gap/equivalence classification and independently measured proposal quality.
- [x] M3.2a: Separate-role/process static triage queue and immutable hash-bound evidence consumed by runtime; no source execution or activation. See FACTORY_STATIC_CHECKS.md/ADR0011.
- [ ] M3.2b: Independently approved isolated behavior/property/replay/resource tests and comprehensive security/dependency/license qualification for Factory bundles.
- [x] M3.2b.1: Separate Factory execution-only reviewer/executor roles, hash-bound plans/waits, actual stdlib Python container tests, timeout/output/stop and checkpoint recovery evidence. See FACTORY_EXECUTION.md/ADR0012.
- [ ] M3.2b.2: Full property/negative/replay/poison/SAST/dependency/license qualification and MCP/Skill/nonstdlib adapters; malicious subject/test anti-tamper validation.
- [x] M3.2b.2a: Host-owned finite-vector JSON comparison in fresh per-input containers after approved unittest execution; real reporting-tamper/early-exit/withholding/revocation/timeout and missing-proof denials. Bindingv2, no SQL migration. See HOST_ORACLE.md/ADR0014.
- [ ] M3.2b.2b: Broader adversarial/property/replay/poison/dependency/license qualification and measured coverage; finite vectors alone do not release a candidate.
- [x] M3.2b.2b.1: Fixed repeat/order/fresh-session replay profile and normalized manifest-poison triage with real execution/publication/signature deny consumers. Bindingv3, no SQL migration. See PROPERTY_QUALIFICATION.md/ADR0015.
- [x] M3.3b.1 + M3.4a DEVELOPMENT SLICE: pure-JSON internal releases, immutable active versions, scoped durable invocation, cross-task reuse, revoke and rollback. Real paid-model sales Tool generation/ABI repair/qualification and two new-task reuses passed. See INTERNAL_REGISTRY.md and ADR0016. Production/general MCP/Skill tiers remain open.

- [x] M3.3a: Independently signed immutable EVIDENCE_ONLY bundles, real public-key verification, live key/review revocation and scoped API/unrelated-task lookup consumers; no activation. See SIGNED_EVIDENCE.md/ADR0013.
- [ ] M3.3b: Independent complete-qualification release approval, production signing custody, registry activation/tenant allowlists/staged rollback.

- [ ] Capability gap classifier and candidate proposal API (exact proposal subset implemented; semantic classifier open).
- [ ] Generates source + tests + MCP manifest + permissions + dependency/SBOM metadata.
- [ ] Sandbox qualification: unit/contract/property tests, fixtures, static analysis, SAST, dependency audit, injection/poison tests.
- [ ] Enterprise risk-tiered approval workflow. Development/internal-demo approval is delegated to the trusted development agent (including its own proposals); model-originated instructions confer no authority. Hash-bound records and sandbox limits remain mandatory.
- [ ] Immutable versioned signed artifact, registry activation, staged rollout, tenant allowlists, rollback and deprecation.
- [ ] Reuse tests from unrelated tasks and recurrent regression, quarantine on drift; score long-term stability by observed success.

## M4 — Credential broker and tenant identity

- [ ] OpenID Connect login, user/tenant/service principal mapping, RBAC + ABAC.
- [ ] OpenBao/Vault-compatible managed encryption, token rotation and scoped delegated OAuth flows.
- [ ] Handle-based tool grants; short-lived tokens only in trusted executor; never LLM context or task logs.
- [ ] Capability authorization includes user + tenant + tool version + permitted action/resource + TTL + approval.
- [ ] Revocation, rotation, escrow/secret leakage alerts, audit and break-glass procedures.
- [ ] Multi-tenant escalation and exfiltration tests.

## M5 — Memory/skill evaluation and enterprise productization

- [ ] Skill registry with versioning, provenance, semantic scope and deterministic applicability tests.
- [ ] Memory pipeline: candidate extraction → normalization → contradiction/dedup → evidence → evaluation → promotion → expiry.
- [ ] Trace/AOC dashboards for quality, budget, tool error/drift, approvals and model use.
- [ ] Commercial provider policy, data residency and PII classification; on-prem/air-gap deployment profile.
- [ ] OSS legal review + SBOM + DPA/third-party notice + customer-specific deployment manifest.
- [ ] Release gates from `ACCEPTANCE_TESTS.md`.

## Priority order inside each milestone

Safety invariant → persistence/API → one integrated scenario → failure handling → tests/evidence → UI polish.

## Typical Codex iteration

1. Read contracts and dependencies; explain the precise boundary being changed.
2. Write tests including deny cases.
3. Implement smallest running workflow.
4. Run tests, lint and smoke tests; record exact output and caveats.
5. Update this file and any ADR; identify next work without expanding current scope.

## Execution work units after M1

Track each unit in DEV_PROGRESS; each requires a running consumer, negative tests and rollback notes.

| Unit | Concrete deliverable | Dependency / release gate |
| --- | --- | --- |
| M2.1 | PARTIAL: granted immutable snapshot/Git import plus actual operator task-local derived-baseline checkout/staged diff implemented; agent-contained original-history checkout pending | No model host shell; qualified agent Git consumer still required |
| M2.1a | IMPLEMENTED: operator-only scoped task Git checkout, actual staged diff and separate-process handoff proof | Derived snapshot baseline, not original-history clone; no execution or new agent privilege |
| M2.1b | IMPLEMENTED DEVELOPMENT SLICE: fixed-image repo_git_status consumer, digest-pinned grants and actual PostgreSQL/worker/Git Docker qualification | User approved exact dev image build/tests; customer redistribution and original-history clone remain open |
| M2.2 | DATA OPERATIONS IMPLEMENTED: one-shot non-root fixed-image runner and actual kernel/resource/egress checks | Not qualification for arbitrary candidate execution |
| M2.3 | PARTIAL: typed list/read/search/inert-patch consumed by durable runtime; approved test tool pending | Pinned runner/tool digests; independent execution approval |
| M2.3a | IMPLEMENTED: durable candidate + exact-bound independent DB-role review, rejection/revoke/expiry, new-worker resume | Development identity only; no candidate execution or production promotion |
| M2.3b | IMPLEMENTED: opt-in reviewed stdlib tests, separate baseline/candidate containers, actual exit/log evidence, cancel/revoke/expiry and checkpoint reuse | Development fixture qualification only; production escape/supply-chain/identity gates remain |
| M2.4a | IMPLEMENTED: actual failed-candidate evidence → immutable parent repair → new independent approval → passing retest; rejection/budget deny | Fixture inference/reviewer; 0004 ancestry and binding v3 |
| M2.4b | Fixed real-repository/live-model benchmark and failure taxonomy | Task-local checkout; provider availability/policy |
| M2.5 | Reviewable PR candidate and explicitly approved external write | Separate scoped grant; no automatic push |
| M3.1 | Capability gap proposal and quarantined bundle API | Candidate cannot execute |
| M3.2 | Contract/fixture/replay/security/license/SBOM qualification | Independent runner/evidence |
| M3.3a | IMPLEMENTED: independent Ed25519 EVIDENCE_ONLY signing, export/import, public/API/cross-task verification, live revocation | No executable admission or release approval; schema0008 |
| M3.3b | INTERNAL SLICE IMPLEMENTED: pure-JSON release/active heads/rollback; complete enterprise qualification and production custody remain open | Delegated development approval; immutable digest, scoped allowlists |
| M3.4 | INTERNAL SLICE IMPLEMENTED: cross-task pinned invocation and output-drift quarantine | Real-model reuse demonstrated; broad business benchmark remains open |
| M4.1 | OIDC principal/tenant mapping and RBAC/ABAC | Cross-tenant deny suite |
| M4.2 | Vault/OAuth scoped handles and trusted executor injection | No credentials in prompts/traces |
| M4.3 | Revoke/rotate/expiry/resource and digest checks | Crash/replay/leak tests |
| M5.1 | Versioned skill and normalized evidence-backed memory pipeline | Candidate review/evaluation/expiry |
| M5.2 | Model residency/classification and explicit hybrid routing | Commercial fallback deny suite |
| M5.3 | Telemetry, quotas, customer install/backup/rollback drills | Fixed SLO and air-gap validation |
| M5.4 | Exact-version SBOM, legal/branding/weights/DPA release review | Explicit company clearance |

M2 data-operation evidence and limitations: [M2_WORKSPACES.md](M2_WORKSPACES.md), [ADR 0002](adr/0002-isolated-workspace.md), `docs/evidence/m2-workspace-demo.json`.

Transport/recovery update: [OPEN_WEBUI_SMOKE.md](OPEN_WEBUI_SMOKE.md), [ADR 0003](adr/0003-chat-transport-and-cleanup.md). Managed-v2 sandbox expiry/reaping closes a verified late-create cancellation leak; no candidate execution permission was added.
