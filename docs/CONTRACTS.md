# API and capability contracts

## Quarantined factory proposal contracts (0005)

`capability_lookup` and `capability_propose` have strict typed inputs/outputs, version0.1.0, maintainer ownership, digest, no egress, bounded failure/timeout metadata. New tasks need server opt-in; clients cannot grant them. Proposal canonically hashes manifest/source/tests/fixtures/dependency/SBOM/license declarations. Closed bounded JSON contract/fixture validation and Python syntax parsing do not execute code or independently validate behavior/security/license. Immutable per-Step receipts recover without duplicate artifacts/events; changed bytes at the same scoped name/version return version_conflict. GET /api/v1/capabilities/{id} is authenticated scoped inspection only. Candidate views are always QUARANTINED/untrusted/noninvokable. MCP/Skill fields describe inert artifacts, not working server connections or runtime instructions. See CAPABILITY_PROPOSALS.md and ADR0010.

## Existing bootstrap endpoints

| Method | Path | Notes |
| --- | --- | --- |
| GET | `/healthz` | Liveness only; does not certify external systems |
| GET | `/v1/models` | Basic OpenAI model list; requires service bearer |
| POST | `/v1/chat/completions` | Non-streaming tool loop, bounded depth, requires bearer |
| POST | `/api/v1/tasks` | Durable PostgreSQL submit/queue; see M1 contracts below |
| GET | `/api/v1/tasks/{id}` | Durable task status/result; dev service token only |
| — | State transitions | Legacy `TaskStore` tests; durable pause/resume/cancel routes below |

## Future external contracts

`TaskSubmit`: `idempotency_key`, `workspace_ref`, `input`, `grant_refs[]`, `model_policy`, `max_cost`, `max_steps`, `timeout_seconds`, `approval_policy`.

`TaskEvent`: `event_id`, `task_id`, `sequence`, `timestamp`, `actor`, `type`, `stage`, `tool_ref`, `model_ref`, `trace_id`, `artifact_hashes[]`, `redacted_payload`, `policy_decision`.

`ToolManifest`: `name`, `semver`, `artifact_sha256`, `input_schema`, `output_schema`, `permissions`, `network_allowlist`, `secret_scope_refs`, `timeout_seconds`, `resource_limits`, `dependencies`, `sbom_ref`, `test_evidence`, `owner`, `approval_receipt`, `status`.

`CredentialGrant`: `grant_id`, `tenant_id`, `principal_id`, `task_id`, `tool_artifact_sha256`, `provider`, `resource_pattern`, `allowed_actions`, `expires_at`, `approval_receipt`, `revocation_status`. Grant IDs are model-visible references; bearer/token material is **never** model-visible.

`MemoryFact`: `id`, `namespace`, `kind` (`fact`/`decision`/`lesson`/`skill`), `content_ref`, `source_refs[]`, `applicability`, `confidence`, `validated_at`, `expires_at`, `owner`, `version`, `status`.

## Required event state machine

`QUEUED → RUNNING ↔ WAITING_APPROVAL → COMPLETED|FAILED|CANCELLED|TIMED_OUT` (with permitted edges defined in code). Worker restart maintains state/event causality; retries do not duplicate side effects.

## Example MCP/Tool manifest

See [`../examples/tool_manifest.json`](../examples/tool_manifest.json). It is a *candidate description*, not active executable code.

## M1 runtime contracts — implemented 2026-11-08

The bootstrap task rows in the earlier table are superseded by the durable runtime routes:

| Method | Path | Behavior |
| --- | --- | --- |
| POST | `/api/v1/tasks` | `prompt`, optional `idempotency_key`, `limits`; transactionally queues a task/event; returns 202 |
| GET | `/api/v1/tasks/{id}` | State, result/error, timestamps, counters, reserved tokens/cost and sequence |
| POST | `/api/v1/tasks/{id}/pause` | Fence work, persist PAUSED checkpoint |
| POST | `/api/v1/tasks/{id}/resume` | PAUSED to QUEUED; terminal and approval waits cannot resume |
| POST | `/api/v1/tasks/{id}/cancel` | Terminal cancellation; repeat cancel is idempotent |
| GET | `/api/v1/tasks/{id}/events` | SSE; Last-Event-ID or nonnegative `after`, optional `follow=false` |

Idempotency-Key header and body must agree when both exist; reusing a key with a different normalized body returns 409. Missing identity is 401; missing/wrong-scope task is 404; invalid transitions/ahead event cursor are 409; malformed cursor/input is 422. Event IDs are monotonically increasing integers per task. Replay is ordered and bounded in 500-event pages. SSE heartbeat comments carry no task data. State/checkpoint/result event writes are atomic.

Implemented state edges: QUEUED to RUNNING/PAUSED/CANCELLED; RUNNING to PAUSED/COMPLETED/FAILED/CANCELLED/TIMED_OUT; PAUSED to QUEUED/CANCELLED. Expired deadlines resolve to TIMED_OUT on claim or heartbeat/step commit. RUNNING lease recovery creates a new run without pretending an uncommitted call succeeded. WAITING_APPROVAL is reserved, not dispatchable or resumable through these APIs; cancellation is permitted. No approval grant is created by a model.

The server fixes the development principal and tenant; it does not trust chat `user`. This is one authenticated service, not a production multi-tenant identity solution. Model policy, repo grants, credential grants and external-write approval are not accepted client authority in M1.

`/v1/models` also exposes `<CALIBURN_MODEL>-durable`. Nonstreaming completion on that model uses the real task queue and requires a running worker. A gateway wait timeout returns a task reference while work continues. See M1_RUNTIME.md for context flattening, budgets and known limitations. The original non-durable model remains available.

## M2 workspace reference and tool transport

`POST /api/v1/tasks` optionally accepts `workspace_ref` (opaque registered UUID only). The server resolves the grant for its fixed development actor/tenant, requires ACTIVE and unexpired status and pins bundle/tool hashes. Missing/wrong-scope/revoked/expired references return 404. Arbitrary host roots, actor/tenant, image, tool permissions and approval fields remain forbidden client authority.

Granted tasks receive typed repo_list, repo_read, repo_search and, only with propose_patch permission, repo_patch. List/read/search operate on a bounded immutable snapshot; patch returns an inert candidate/hash/diff with approved=false and executable=false. There is no repo_test, shell, clone/fetch, publish or self-approval tool. Strict input/output schemas and failure modes are recorded in sandbox/contracts.py TOOL_MANIFESTS.

The internal database queue binds each request/result to task/step/task lease/controller lease, with bounded recovery and completed-result reuse. SANDBOX_QUEUED and SANDBOX_COMPLETED events include step/request/workspace or immutable image references. API authentication remains a development service token; this is not production tenant identity. See M2_WORKSPACES.md for complete limits/commands.

## Durable chat stream compatibility

`POST /v1/chat/completions` on `<CALIBURN_MODEL>-durable` now accepts stream=true. Before response headers: authentication/model/role/context checks and durable submission. SSE frames: role with task/event reference, final committed content, finish_reason=stop, `[DONE]`. After-header task failure emits a bounded error frame carrying the task reference. This is completion-level framing; upstream token increments are not forwarded. The original direct M0 model still rejects streaming with 501.

Early HTTP disconnect does not cancel independent durable work. Task lookup and `/api/v1/tasks/{id}/events` continue to require bearer authorization; Last-Event-ID remains a per-task integer. Actual socket disconnect/replay and browser smoke are recorded in OPEN_WEBUI_SMOKE.md. Product step/tool timeline UI and production tenant identity are not implied.

## Candidate review contracts

repo_patch now returns a server-generated candidate_ref alongside its inert typed result; runner-supplied candidate references are denied. Candidate persistence and result/event publication share the same fenced transaction. request_review is a separate operator workspace permission and is absent from existing/default grants.

repo_request_review accepts only candidate_ref and plan_ref (strict extra-forbid schema). It binds exact task/tenant/actor/workspace/source/plan/image/tool hashes and pauses the task. Successful resumed output uses the typed ReviewResult schema: APPROVED_FOR_SANDBOX_TEST, request/hash, sandbox_test_only scope and source_executed=false. This is not an execution result. The call consumes one tool attempt only after approval. Bad/revoked/expired scope fails closed.

Authenticated GET /api/v1/tasks/{id}/reviews returns scoped hash/status summaries. No approval HTTP write endpoint is exposed; general resume returns 409 while waiting. The independent PostgreSQL current_user, mapped principal, exact hash and expiry authorize CLI decisions; reviewer fields from source/model/client cannot authorize them. See CANDIDATE_REVIEW.md for authority limitations and ADR 0004 for the migration.

## Reviewed test execution

repo_test accepts only request_ref; command, source, image, test content and authority flags are forbidden input. It requires execute_reviewed_tests in the operator-owned workspace and task policy, separate independent approval and a matching immutable supervisor image. Binding v2 includes that permission and driver/control implementation hashes. Default data supervisor excludes this job type. Request, claim, pre-source dispatch, heartbeat, polling and result publication recheck authority/leases. Old digest-pinned tasks/approvals are refused rather than repinned silently.

Typed TestData includes request/binding/image hashes, separate TestRun baseline/candidate outcomes (PASSED/FAILED/TIMEOUT/OUTPUT_LIMIT, exit, bounded untrusted log, source/plan hash), source_executed=true and production_approved=false. ok=true means evidence was produced, not that the candidate passed. The review-only observation retains source_executed=false; summary inspection reports committed execution true, unknown attempted execution null, otherwise false. Timeouts/cancellation cannot establish that code never started. No arbitrary shell/dependencies/external writes or production activation are added. See REVIEWED_TESTS.md and ADR 0005.

## Parent-based repair

repo_patch optionally accepts parent_candidate_ref (36-character reference, null/omitted means original snapshot). The server resolves only same-task/workspace/actor/tenant immutable candidates, validates all ancestor bundle/base hashes and limits a chain to 32 candidates. expected_sha256 must match the chosen parent's file; stale original hashes fail. Other files inherit the parent's content. No host path or caller-provided parent files are accepted. Migration 0004 adds a nullable self-FK plus PostgreSQL cross-scope INSERT trigger; old roots remain unchanged. Binding v3 adds parent_candidate_ref and patch_source_sha256; a child's changed hash requires a new independent decision. Existing task budgets include all attempts and survive multiple approval waits. See REPAIR_LOOP.md and ADR 0006.

## Operator checkout contract

The checkout CLI accepts task reference, optional same-task candidate reference and an explicit existing private output root. It has no model tool/HTTP command route. Server-side read/grant/TTL/actor/tenant/bundle/ancestry checks produce bounded inert files. A strict versioned CheckoutReport records original source provenance separately from the actual reconstructed baseline Git commit/tree, candidate index tree and patch digest. source_executed and production_approved are always false. Source/config instructions cannot authorize commands; only fixed operator Git operations are available. Fresh output/replay, publication-time revoke/known-credential checks, bounded command time/output and exact-owned partial cleanup are implemented. No schema migration or original-history/agent checkout completion is implied; see TASK_CHECKOUT.md and ADR 0007.

## Prepared Git data consumer (qualification pending)

repo_git_status accepts only optional candidate_ref (strict extra-forbid). An explicit new operator --git-image grant adds git_inspect and pins its immutable digest in workspace provenance/task policy; existing/default workspaces do not gain it. Input images/commands/network/approval/actor fields cannot authorize it. Server request/claim/heartbeat/result checks bind candidate, source, ancestry, scope and image. Existing data/test supervisors exclude Git jobs. Separate fixed Git supervisor uses no agent host process capability and requires live admission before source delivery.

Typed GitData includes source hashes, actual derived baseline commit/tree, candidate index tree, changed paths, bounded diff/full SHA256/truncation flag, Git version and literal source_executed=false. The implementation/runner/control digests are pinned. Current tests use actual Git and DB/worker with labeled fixture Docker transport; real Git container build/kernel/timeout/cancellation checks remain skipped pending explicit user approval. No source execution, original-history clone or customer distribution is implemented by this contract. See GIT_DATA_APPROVAL.md/ADR0008.

## Task console and read-only history

Public /tasks/ui plus three allowlisted assets contains no credential/task content. All dynamic reads/actions use the existing authenticated task endpoints. GET /api/v1/tasks/{id}/history accepts after_step>=0, run_offset0..100000 and limit1..100. It returns limits/deadline, typed RunView/StepView metadata and next cursors; no raw step input/output/messages or lease token. Actor/tenant stays server-owned; wrong scope/missing task returns404, absent bearer401, bad cursors422 and known credential-bearing projection502 without raw content. Reads neither claim work nor mutate state.

The browser uses Authorization + Last-Event-ID with same-origin fetch SSE. UTF8/chunk framing is bounded; frames must match task/sequence/type, duplicates are ignored and gaps never advance the accepted cursor. Network reconnect retains the in-memory cursor; a new manual session/reload replays from0. Recent view is capped at250 events, with server history intact. Source/result text is literal. Pause/cancel/resume are the existing server controls, not approval authority; WAITING_APPROVAL has no general resume/approve button. See TASK_CONSOLE.md and ADR0009 for packaging, token lifetime and limits.

## Independent static reports (0006)

Version0.2.0 capability_check accepts strict bundle_ref UUID only, under a separate server grant. A per-Step durable request binds actor/tenant/bundle/checker/deadline. Typed result includes report_ref/report SHA and StaticReport: BLOCKED or REVIEW_REQUIRED, source_executed=false, activation_eligible=false, execution NOT_RUN, security INCOMPLETE, dependencies UNVERIFIED, license UNREVIEWED, <=128 code/path/line findings with truncation. Reports are independently stamped and immutable; none is PASS or an execution/activation grant. Authenticated GET /api/v1/capabilities/reports/{id} exposes scoped provenance. Existing factory tools advertise only task-permitted definitions. See FACTORY_STATIC_CHECKS.md.

## Factory execution review/tests (0007)

Typed capability_request_execution(plan_ref) and capability_execute_tests(request_ref) require a separate server-only new-task grant and EXEC_DIGEST. Reviewer-only decisions bind exact source/static report/plan/image/implementation hashes and Task limits. Review result says APPROVED_FOR_FACTORY_SANDBOX_TEST with source_executed=false/production_approved=false. ExecutionResult has consistent ok/data/error fields; positive ExecutionEvidence includes actual executor role, bounded TestRun exit/status/output/source/plan hashes and immutable image/request/binding, with source_executed=true, production_approved=false, security INCOMPLETE and license UNREVIEWED. Successful transport may contain failed/time/output-limited tests. Failed/abandoned dispatch may have unknown execution. Generic sandbox transport is projected into this strict Factory contract, excluding unrelated candidate_ref fields. GET /api/v1/tasks/{id}/factory-execution-reviews supplies up to20 authenticated scoped summaries without source/lease values. No self-approval, commands/images/secret/authority fields or cross-task request reuse. See FACTORY_EXECUTION.md/ADR0012.


## Signed evidence inspection (0008)

SignedEvidence contains algorithmEd25519, a bounded versioned EVIDENCE_ONLY statement, canonical statement SHA256 and128 lowercase hex signature. Full source/test/manifest/dependency declarations and independently reviewed actual execution evidence are bound to actor/tenant/key/time. Production approval is forbidden. Authenticated GET /api/v1/capabilities/artifacts/{id} returns verified envelope/admission with no-store;404scope/missing,409trust/integrity denied. Candidate lookup includes at most5 scoped VERIFIED_EVIDENCE/UNTRUSTED ArtifactSummary values; can_invoke and activation_eligible are alwaysfalse. There is no activation API. See SIGNED_EVIDENCE.md/ADR0013.

Git contract update: after explicit development approval, the fixed Git image and actual Docker isolation/failure/worker path were exercised (GIT_DATA_APPROVAL.md). Earlier pending/skipped descriptions above are historical; no original-history cloning or customer redistribution permission was added.


## Factory execution bindingv2 host evidence

The immutable full plan includes reserved caliburn_host_oracle.json: versionhost-oracle-v1, case_sourcebundle_declared|operator, exactentrypoint and1..8 unique bounded typed input/expected vectors. Owner registration validates both sides against the declared supported contract. Bindingv2 adds oracle_sha256/oracle_cases/child_plan_sha256. Initial child payload excludes the metadata and binds the child-only plan hash. isolation.child_test_run preserves actual child source/hash/exit/output; aggregate TestRun names the complete reviewed plan. isolation.host_oracle requires exact vector hash/count, checked<=total and complete counts forPASSED. Durable PASSED/new signatures/imports require matching complete host and child evidence. Oracle comparison failure is ok=false/errorfactory_oracle_failed with original exit0 retained as untrusted evidence, never a fabricated failed process exit. All subject JSON is untrusted; extra pass fields/duplicate keys/nonfinite/depth>64/bytes>32768 deny. No activation authority. See HOST_ORACLE.md.


## Repeat/order/replay proof (bindingv3)

New OraclePlan.versionhost-oracle-v2 fixes profile repeat-order-replay-v1. Invocation wire uses inputs1..16 and values of matching length, with each value frozen per call. Four fresh sessions cover two forward/two reverse replays and two successive calls per vector. Binding pins profile/sessions4/observations8*N. Proof records complete vector validation, fully passed sessions and successfully compared observations; PASSED requires all4/8*N. Current durable publication/signing/import denies legacy/partial profiles; historicalv2 evidence is readable without upgrading authority. Original work/time/output/secret constraints remain. PROPERTY_QUALIFICATION.md.
