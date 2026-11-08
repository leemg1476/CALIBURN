# Target acceptance tests (must be automated before enterprise release)

Factory proposal increment (test_factory.py): actual worker/API and PostgreSQL/SQLite proposal/inspection, scoped unrelated-task reference reuse, candidate invocation deny, default/server-only grant and tool budget deny, live lease/deadline/cancel/pause/revision/known-secret denial, exact input replay and version conflict/contention, SQL immutability/runtime-role permissions, contract/path/fixture/lock/authority denial, inert Tool/MCP/Skill payloads and actual child-process death after proposal commit with replacement-worker receipt recovery. Scripted models/synthetic identities are fixtures; no generated test is executed or counted as qualification. Enterprise semantic gap, security/behavior qualification, independent signing/activation and qualified invocation reuse remain open.

## A. Multi-step coding agent

- [ ] Open WebUI task arrives with a verified principal and repository grant.
- [ ] The agent checks out repo in isolated workspace; inspects files; patches code; runs tests; reports diff and evidence.
- [ ] Agent restarts mid-job, resumes from durable event state without duplicating external writes.
- [ ] Abort and time/step/token/cost budget exhaustion stop work; task state and artifacts remain recoverable.
- [ ] Failing test triggers bounded repair attempts; unresolved failure is reported honestly.
- [ ] Read-only task cannot write to repo; no arbitrary host process or network requests.

## B. Tool/MCP lifecycle

- [ ] Need for new tool is detected and proposed with manifest, typed schemas, dependency/license list, tests and permission requirements.
- [ ] Candidate cannot execute in privileged API or automatically enter active registry.
- [ ] Tampered artifact, self-approval, missing scans and incompatible schema each block promotion.
- [ ] Approved `name@version+hash` can be invoked from a different task and its output schema is validated.
- [ ] Regression suite detects drift; quarantines failed version and supports rollback with old task pinning.
- [ ] Repeated tasks show measured success rate and cost benefits against no-reuse baseline.

## C. Credential broker

- [ ] Tool obtains delegated short-lived auth for only its permitted tenant, actor, resource and operation.
- [ ] Wrong user/tenant, expired/revoked grant or changed tool digest returns deny.
- [ ] No raw secrets appear in LLM request, trace, logs, Open WebUI message or error response.
- [ ] Rotation and revoke invalidate subsequent operations; admin/master credentials never exposed to model.

## D. Model routing

- [ ] Local and commercial providers operate under a unified model contract with real tool call fixtures.
- [ ] Disabled commercial fallback cannot leak a request when local inference is unavailable.
- [ ] Classification and residency policy prohibits sensitive task egress to disallowed endpoints.
- [ ] Tool-call JSON errors, provider timeout, model content-limit and budget-limit outcomes are observable.

## E. Platform operations and licensing

- [ ] Tenant RBAC/ABAC; event/audit access boundaries; audit immutable retention policy.
- [ ] SBOM and OSS/weights/API licenses reviewed for each customer deployment.
- [ ] UI branding/export distribution explicitly authorized for chosen UI version.
- [ ] Installation/upgrade/backup/rollback drills completed including offline customer profile.
- [ ] High-volume run performs within documented cost and latency SLO.

## Implemented bootstrap smoke tests

- [x] Bearer token denied when missing/wrong.
- [x] Bounded safe-tool loop.
- [x] Invalid tool calls do not execute arbitrary function/source.
- [x] State transition validation with persisted task record.
- [x] OpenAI-compatible non-streaming response shape.

These checkboxes should only be marked by actual automated checks, not a plan or model assertion.

## M1 automated backend evidence — 2026-11-08

- [x] Real PostgreSQL queue/worker multi-step fixture-model to reviewed-tool execution.
- [x] Process dies after tool returns before commit; natural lease expiry and new worker recover.
- [x] Committed model/tool checkpoints are not repeated; retry attempts consume limits.
- [x] Concurrent duplicate submit/claim, stale-lease write deny and DB event mutation deny.
- [x] Pause/cancel during a model request; resume/terminal-state rules and wall/call timeout.
- [x] Model/tool/token/cost/retry limits, invalid provider protocol and unknown/poisoned tool denial.
- [x] Authorized SSE replay/reconnect with contiguous sequence IDs, including actual HTTP sockets.
- [x] Migration downgrade/upgrade round-trip in isolated test schemas.
- [x] Known configured platform secret rejection; generic provider errors expose no response body.

Inference is mocked. These checks do not check off the target coding-agent, broker, factory, real model-routing, Open WebUI browser, legal-clearance or enterprise release criteria above. See DEV_PROGRESS.md and recorded demo JSON for exact evidence.

## M2 data-operation checks (not full coding-agent acceptance)

- [x] Real task worker -> PostgreSQL sandbox queue -> separate trusted supervisor -> fresh container -> durable result/event.
- [x] Real kernel/cgroup checks: UID 10001, no capabilities, seccomp, no-new-privileges, read-only root, only loopback interface, no Docker socket, bounded memory/CPU/PID.
- [x] Typed source list/read/search and inert patch, exact base-hash/stale-base refusal; source is never imported/executed.
- [x] Traversal/credential paths/oversize/collision/binary input denial; explicit safe project dotfiles supported.
- [x] Workspace actor/tenant scope, read-only/propose-patch grant, TTL/revoke, controller retries, stale result rejection and pause/cancel/revoke container cleanup.
- [x] Runtime role cannot INSERT/UPDATE/DELETE workspace grants (actual PostgreSQL SQLSTATE 42501).
- [x] Local immutable Git commit/blob import ignores dirty working tree and denies partial clones/alternates/includes; no remote request.
- [x] Separate-process actual HTTP/SSE demo with scripted fixture inference; four sandbox operations produce an unapproved/unexecuted diff.

Actual task-local checkout, approved test execution, independent test-based repair and real-repository longitudinal quality remain unchecked above. Evidence is not a model quality score or arbitrary-code sandbox certification.

## Actual UI and lifecycle evidence

- [x] Original pinned Open WebUI browser shows a durable fixture answer, matched to actual PostgreSQL task/worker/events.
- [x] Durable OpenAI chat SSE success/error/auth/input contracts; early socket disconnect preserves the queued task and later result/replay.
- [x] Real delayed Docker create after cancellation before process-handle return is owned/removed.
- [x] Restart reaper removes only expired marked no-host-data sandboxes and preserves active/malformed/foreign instances.

No enterprise principal/repository-grant, timeline, live model quality or generated-code approval/execution checkbox is satisfied by these narrow checks. Evidence and exact commands: DEV_PROGRESS.md, OPEN_WEBUI_SMOKE.md and ADR 0003.

## Candidate review subset

- [x] Actual PostgreSQL role/trigger/ACL checks: self-approval and forged reviewer field denied; runtime cannot mint plans/reviewer mappings/decisions/revocations.
- [x] Exact candidate/plan/image/tool binding; immutable rows, wrong hash, cross-task candidate, revoked workspace, expiry, replay, cancel and timeout denial.
- [x] Actual Docker inert patch, durable WAITING_APPROVAL, separate-role inspect/decision CLI subprocess and new-worker resume without repeating the patch or resetting budgets; scripted inference/synthetic reviewer only.
- [x] API review summaries require authentication; ordinary resume/approve cannot bypass the gate.
- [ ] Independently authorized candidate test execution, repair loop, cryptographic signing and production promotion remain unimplemented.

These checks verify review workflow behavior, not a human approval or generated-source execution qualification. See CANDIDATE_REVIEW.md and ADR 0004.

## Reviewed stdlib execution subset

- [x] Actual independently approved baseline failure/candidate success; separate fresh containers, identical registered unittest plan, actual exit/log/hash evidence consumed by the worker.
- [x] Explicit execution grant; data-only supervisor excludes test jobs; missing grant/wrong image/expiry/stale controller deny dispatch/publication.
- [x] Final admission check before source delivery and between variants; actual active container removed on pause/cancel/revoke.
- [x] Timeout, output overflow, process exception, denied network/root write and absent platform credential environment; no host mounts or arbitrary commands.
- [x] Interrupted worker checkpoint reuses committed sandbox evidence without another test supervisor; failed attempt remains charged to budget.
- [ ] Production arbitrary-code escape/rootless/microVM/supply-chain qualification, iterative failed-candidate repair, task-local Git checkout and fixed real-repository/live-model benchmark.

Mechanism tests use fixture inference and synthetic reviewer roles; they are not actual human approval or production tool promotion. Exact evidence and command results are maintained in DEV_PROGRESS.md and REVIEWED_TESTS.md.

## Evidence-driven repair mechanism

- [x] Actual failed candidate test log → same-task parent patch → new independent approval wait → actual passing child retest; original baseline remains failing.
- [x] Old digest cannot approve the child; second rejection or cumulative tool-budget exhaustion prevents a second execution.
- [x] Full parent bundle preserves changes in other files; stale original hash and cross-task parent are denied, including direct PostgreSQL INSERT.
- [x] Chain bounded to 32 candidates; migration 0004 preserves a populated 0003 root on PostgreSQL and SQLite.
- [ ] Real task-local Git checkout, fixed real-repository/live-model repair benchmark and enterprise production qualification.

Source/model/reviewer identities are deterministic fixtures. Actual source data queue, container tests, database decisions, worker checkpoints and budgets run for real. See REPAIR_LOOP.md and ADR 0006.

## Operator task Git checkout subset

- [x] Actual Git detached checkout from the authorized reconstructed baseline; exact HEAD/index/blob/staged diff identities and manifest/patch hashes.
- [x] Pinned original Git import despite dirty source, excluded-file scope, same-task candidate and foreign actor/tenant denial; original repository unchanged.
- [x] Source .gitattributes/global config cannot transform bytes or invoke hooks/filters/textconv; credentials are not forwarded or logged.
- [x] Fresh-directory replay and no partial output after timeout/cancel/publication-time revoke/known-credential denial, including actual Windows readonly Git object cleanup.
- [x] Separate-process actual HTTP/API/worker/Docker candidate followed by operator checkout CLI, retained offline review package and independently rechecked Git hashes.
- [ ] Agent-contained Git workspace/original-history checkout and fixed real-repository/live-model benchmark remain unimplemented.

This operator export adds no model host-shell permission, source execution, candidate approval or upstream history clone. See TASK_CHECKOUT.md and ADR 0007.

## Prepared Git data boundary

- [x] Actual DB/worker/shared host-Git consumer produces scoped checkout/index/diff; Docker transport explicitly fixture-labeled.
- [x] Separate image-pinned permission, existing-data consumer exclusion, wrong-image/cancel/revoke/missing-admission/input-authority denial.
- [x] Existing operator checkout behavior preserved by shared stdlib extraction.
- [ ] Git dev-image build and package inventory/license/security inspection — awaiting explicit user approval.
- [ ] Actual Git container kernel/attribute/timeout/cancel and worker qualification — opt-in tests written but skipped pending image.

No container qualification or full agent-contained Git milestone is marked complete by host/fixture tests. See GIT_DATA_APPROVAL.md and ADR0008.

## Independent task timeline

- [x] Actual PostgreSQL/browser/separate-worker task shows3 steps,1 run,2 model/1 tool calls,result42 and11 unique events.
- [x] Browser pause/resume and API restart recovery preserve state/cursor without duplicate visible events; queued/review-wait cancel and terminal controls verified.
- [x] Read-only authenticated/paginated history with exact output hashes, principal/tenant denial, no raw step content/leases and known-credential metadata refusal.
- [x] Wrong-token denial, cleared token field, literal HTML-like prompt/result with zero executable elements, narrow-screen no-horizontal-overflow and self-hosted CSP/assets.
- [x] Built-in Node SSE UTF8/CRLF/frame/cursor/duplicate/gap/control tests; actual wheel contains all4 console assets.
- [ ] Enterprise OIDC/individual session authorization, Open WebUI embedded navigation and production scale/security qualification remain open.

This console is original independent CALIBURN UI; existing Open WebUI source/branding is untouched. Actual inference remains a fixture. See TASK_CONSOLE.md and ADR0009.

## Factory static triage evidence

test_factory_checks covers deterministic bounded inert parsing, a real separate verifier OS process/DB role servicing the waiting runtime worker, authenticated/cross-scope report lookup, role offboarding and forbidden runtime-write privilege expansion, stale leases/recovery and receipt reuse, contention/paused-job nonstarvation, cancellation/deadline/revision/retry budgets, forged SQL/static-success claims, report immutability and default/tool-call/timeout denials. Existing runtime-role migration tests deny report/mapping writes. SQLite cannot act as verifier. Models/identity are synthetic fixtures; PostgreSQL/process/queue/worker behavior is real. No generated test or source runs; full sandbox/property/security/dependency/license qualification and promotion remain open.

## Factory reviewed sandbox test subset

test_factory_execution uses real PostgreSQL roles/processes/Docker with synthetic model/principals: good/wrong candidates, independent extra case plus strict fixture probe, rejection/revocation/disabled-role/expiry/cancel before dispatch, running-container revoke/cancel/pause cleanup, actual child worker exit73 after result persistence and natural lease recovery without redispatch, timeout/output limit, server-only flag, cross-actor/tenant/plan/image denial and unrelated wait nonstarvation. Runtime-role migration checks deny plan/role/decision/revocation/result writes. Actual SQL temp-map poisoning tests cover Factory execution, Factory static and repository reviewer authority after disablement. No live-model quality, complete SAST/property/anti-tamper/license certification, signing or registry activation is claimed.


## Evidence signing and paid smoke additions

- tests/test_signed_evidence.py: real Ed25519 tamper/key/expiry/scope/purpose/algorithm denial; real PG/Docker completed execution → distinct signer process → verified export/import/API/unrelated-task lookup; revocation/ACL/self-sign/TEMP-map/immutable-record denials. Synthetic pure-crypto fixtures are labeled and never persisted as platform evidence. Passing evidence must still deny activation/invocation.
- tests/test_llm.py: explicit API-file alias/config rejection, secret-free Settings repr, official Luna Chat transport parameters and header/body separation; HTTP transport is mocked and no real credentials are loaded by pytest.
- scripts/live_llm_smoke.py: separately opted-in real paid two-stage tool smoke and persisted cumulative50,000-token/100-call ledger. Observed3calls/745tokens/COMPLETED47 in docs/evidence/live-llm-smoke.json; not a repository-coding benchmark.
- Approved CALIBURN_GIT_TEST_IMAGE now exercises actual pinned Git container/isolation/time/cancel paths rather than skipping them; package/copyright inventory retained.


## Host-owned qualification observations (v2)

Actual tests/test_factory_oracle.py drives separately approved PG/Docker candidates with unittest assertion/result monkeypatches and forced SystemExit0 in reporting. A real child exit0 must still yield host rejection and denied signature for wrong observations. Additional success uses two operator vectors and captures both payload phases to prove expected literal/metadata withholding. Oracle-phase revoke/timeout, bare PASSED durable receipt denial, invalid operator vectors and hostile JSON/frame/type checks are covered. No candidate code executes on the host. Full Factory execution/signature/replay/cancel/scope regression must also pass with the new immutable image. Models/principals are scripted development fixtures; no paid call or enterprise-identity/full-qualification claim.


Repeat/order/replay addition: tests/test_factory_properties.py uses actual approved PG/Docker source to reject first-call-only correctness and reverse-order-dependent results after real unittest PASS; counts four distinct invocation containers and denies missing replay/short count/legacy downgrade before accepting genuine proof. Four actual verifier/report/plan-denial paths cover fullwidth, zero-width, Korean metadata and source-name shadowing. Inference/identity fixture limits remain explicit; no general semantic-quality or commercial clearance claim.
