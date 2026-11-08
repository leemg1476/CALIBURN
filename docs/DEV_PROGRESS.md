# M0 analysis and execution ledger

## M0 — 2026-11-08
- Read AGENTS, INIT, start prompt and all 11 initial docs; inspected all source/tests/deployment.
- Baseline: `.venv/Scripts/python.exe -m pytest -q`: **16 passed**, one upstream TestClient deprecation warning.
- Host default Python 3.10 cannot install required project; isolated Python 3.12.12 environment created via `uv venv --python 3.12 .venv`.
- Implemented: single-service dev bearer, nonstreaming OpenAI facade, fixture/static tools, upstream adapter, SQLite metadata.
- Missing: durable dispatch/recovery/SSE, sandbox, factory, identity/broker, evaluated memory, commercial routing policy, actual Open WebUI smoke.
- This directory has no `.git`; no commit, branch or clean-tree evidence can be claimed.

## M1 work units
- [x] Runtime schema and migration (Task, Run/lease, Step, Event, attachment, budget, actor/policy).
- [x] Transactional persisted queue, idempotent submission, locked claim, fencing, heartbeat.
- [x] Separate async worker with persisted model/tool checkpoints and conservative retry budgets.
- [x] Authorized API pause/cancel/resume, SSE replay and reconnect.
- [x] PostgreSQL integration, abrupt termination, concurrency and failure tests.
- [x] Migration/rollback/demo commands and evidence.

No live paid models or external writes authorized. Fixture model is mocked inference; PostgreSQL/worker/API were tested as real components. M1 tools are reviewed read-only demonstrations; generated source remains non-executable. No Open WebUI source/branding changes.

## M1 test and deployment record — 2026-11-08

Implemented: runtime contracts/schema/store/worker/API/redaction; PostgreSQL queue and append-only events; lease fencing/heartbeat and natural crash expiry; bounded checkpoints, pause/cancel/resume; SSE replay/reconnect; OpenAI durable adapter; conservative reservations; typed reviewed static tool contracts/digests; known platform-secret guard; separate migration/runtime DB roles; offline Compose deployment and PostgreSQL-backed CI.

Mocked: all recorded inference, plus synthetic provider errors/HTTP transport fixtures. Arithmetic/clock execution, DB, worker processes, transactions, termination and HTTP/SSE sockets are real. No paid API was invoked.

Not built/verified: actual Open WebUI browser/timeline; independent approval evaluator; real repo coding sandbox/tools; factory/registry activation/signing; OIDC/Vault and enterprise tenant isolation; evaluated memory/skills; policy-driven hybrid routing; vendor invoice accounting; customer load/HA/immutable retention/backup drills; license/SBOM/customer branding clearance. WAITING_APPROVAL is reserved/fail-closed, not an implemented approval workflow.

### Commands and outcomes

- `uv venv --python 3.12 .venv` and `uv pip install --python .venv/Scripts/python.exe -e '.[dev]' sqlalchemy alembic 'psycopg[binary]'`: environment installed (Python 3.12.12). Runtime dependencies subsequently declared in pyproject.
- Baseline `python -m pytest -q`: failed under host Python 3.10 because project was not installed. Corrected to isolated Python 3.12; baseline **16 passed**.
- Disposable loopback PostgreSQL: `docker run --detach --rm --name caliburn-m1-postgres --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=caliburn_test --publish 127.0.0.1:55432:5432 postgres:17-alpine`.
- Set `CALIBURN_TEST_DATABASE_URL=postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test` before `.venv/Scripts/python.exe -m pytest -q`. Each PostgreSQL case uses an isolated UUID schema and actual Alembic migration; SQLite cases do not claim PostgreSQL concurrency.
- Intermediate defects corrected: task-submit response nullable defaults; lint findings; negative configuration test teardown re-reading deliberately invalid settings. A subsequent complete suite must pass before acceptance.
- `.venv/Scripts/python.exe -m ruff check src tests migrations scripts`: PASS.
- `.venv/Scripts/python.exe -m ruff format --check src tests migrations scripts`: PASS.
- `.venv/Scripts/python.exe -m compileall -q src migrations scripts`: PASS. No dedicated type-check configuration exists; no mypy/pyright pass is claimed.
- `.venv/Scripts/python.exe -m alembic upgrade head`: PASS against real PostgreSQL. Downgrade/reapply tested only in isolated schemas, without touching M0 data.
- `.venv/Scripts/python.exe scripts/demo_runtime.py`: PASS with actual API/worker child processes and HTTP sockets, task COMPLETED, model calls 2, tool calls 1, sum=5; SSE prefix 1..3 then reconnect 4..9. Evidence: `docs/evidence/m1-live-demo.json`.
- `docker compose -p caliburn-m1-verify up --build --detach`: PASS, database healthy, migration exit 0, non-root API/worker started. Verified durable chat sum 20+22=42; DB principal `caliburn`, superuser=false, CREATE TABLE denied. Runtime does not receive database administrator credentials. Credentials were ephemeral and not written to code/log evidence.

Final full-suite result is recorded below after final-source validation. The upstream TestClient/httpx deprecation warning is known; it does not fail tests. Git operations remain unavailable because the supplied directory has no Git metadata. No commit/push/PR or external write was attempted.

### Migration and rollback

See M1_RUNTIME.md and ADR 0001. New namespace only; existing SQLite is retained and never auto-enqueued. Stop dispatch and back up before an upgrade; stop all processes and preserve evidence before any approved destructive downgrade. Test rollback was exercised in disposable schemas. Compose stop preserves its named volume; do not delete a customer volume as a rollback shortcut.

### Next priority

M1 UI smoke remains an explicit open item. M2 starts with a real isolated runner and deny-path verification, then a typed repo-inspection/patch/test consumer; no host shell, Docker socket, administrative secret, broad network grant or unreviewed generated code may be introduced to shortcut it. M2-M5 work units are now listed in IMPLEMENTATION_PLAN.md.

### Final validation

- Final-source `.venv/Scripts/python.exe -m pytest -q`: **58 passed, 2 skipped, 1 warning**, no failures/errors (18.88s). Both skips are intentionally SQLite instances of PostgreSQL-only claim/immutability and concurrent-idempotency tests; their real PostgreSQL instances passed. No PostgreSQL integration test was skipped with the configured test DSN.
- Final `ruff check`, `ruff format --check` (25 files) and `compileall`: PASS.
- Final real-socket demo: COMPLETED, 2 model calls + 1 tool call, sum=5, replay IDs 1..9. The demo terminated its own API/worker processes.
- Final Compose rebuild succeeded; its first output-capture helper encountered Windows cp949 decoding of Docker output. Direct final-container verification then passed and confirmed the image API source SHA256 matches the workspace. This was output decoding, not a reported deployment success without verification.
- `docs/evidence/m1-compose.json`: final-image task COMPLETED, 2 model calls + 1 tool call, sum 20+22 verified, runtime role caliburn, superuser=false, schema CREATE denied. Real socket evidence: `docs/evidence/m1-live-demo.json`.
- Verification containers are stopped after validation. Compose's named DB volume is retained; the separate --rm PostgreSQL test container is disposable. No user data/workspace/repository was deleted.

### Changed implementation files

- `src/caliburn/runtime/{contracts,schema,store,worker,api,redaction}.py` and package initializer: implemented runtime vertical slice.
- `src/caliburn/{app,config,llm,agent,tools}.py`: durable adapter, configuration/output ceilings, typed tool output/metadata, credential guards; M0 contracts/task_store retained.
- `migrations/env.py`, `migrations/versions/0001_runtime.py`, `alembic.ini`: schema rollout and isolated round-trip validation.
- `pyproject.toml`, `Dockerfile`, `compose.yaml`, `deploy/001-runtime-role.sh`, `.dockerignore`, `.env.example`, `.gitignore`, `.github/workflows/ci.yml`: dependency/deployment/CI and credential boundary configuration.
- `tests/test_runtime.py`, `tests/worker_crash_fixture.py`, `tests/test_llm.py`, existing agent/API/store tests and fixtures: runtime/failure coverage; existing files also received formatter normalization.
- `scripts/demo_runtime.py`, evidence JSON, README, M1 runbook, progress/plan/architecture/security/contracts/acceptance/Korean overview, license dependency note and ADR 0001: reproducibility and honest implementation status.

Backend M1 is implemented and verified; M1 UI smoke/timeline remains unchecked. The overall platform goal remains active. Next unit is M2 runner isolation with a real consumer and deny-path evidence, followed by repository tools; approval, identity and license gates remain as documented.

## M2 workspace execution slice — in progress

- [x] Bounded server-registered immutable file snapshots with actor/tenant scope, digest, TTL and read/propose-patch permissions.
- [x] Trusted local Git object snapshot import from a full commit; no lazy fetch, hooks, replacement objects, alternate stores or model-selected host paths.
- [x] Durable sandbox request/result queue, task/step/controller lease fencing and bounded recovery.
- [x] Separate trusted host supervisor and fixed immutable-image per-request container, without agent Docker privileges or host mounts.
- [x] Typed list/read/literal-search/inert-patch tools consumed by the real durable runtime worker.
- [x] Negative cases for traversal, scope, read-only grant, expiry/revoke, controller retry/fencing, timeout, pause/cancel and credential escaping.
- [x] Final-source full regression and separate-process demo evidence for this slice.
- [ ] Actual task-local Git checkout, independently approved candidate test execution and repair-loop benchmark.
- [ ] Approval-gated external writes; Open WebUI browser/timeline remains unverified.

Implemented boundary and migration: ADR 0002. No source candidate executes in this slice. Plain directory import is an explicit operator action over a quiescent directory, not a model capability or an adversarial filesystem crawler. The default application does not start a privileged supervisor. Current code adds no new dependency to the runtime/runner image; operator Git remains outside it. Existing Open WebUI branding and distribution gates are unchanged.

### M2 validation record — 2026-11-08

The preceding goal turn made progress (implemented and verified M1). This continuation inspected the current files/process state and implemented the next M2 data-operation units, without redefining the overall platform goal as this subset.

Exact commands:

```powershell
docker run --detach --rm --name caliburn-m2-postgres --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=caliburn_test --publish 127.0.0.1:55432:5432 postgres:17-alpine
docker build --file deploy/sandbox/Dockerfile --tag caliburn-sandbox:m2 .
$env:CALIBURN_SANDBOX_TEST_IMAGE = docker image inspect caliburn-sandbox:m2 --format '{{.Id}}'
$env:CALIBURN_TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests migrations scripts
.venv/Scripts/python.exe -m ruff format --check src tests migrations scripts
.venv/Scripts/python.exe -m compileall -q src migrations scripts
$env:CALIBURN_DATABASE_URL = $env:CALIBURN_TEST_DATABASE_URL
$env:CALIBURN_API_TOKEN = [guid]::NewGuid().ToString('N')
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/demo_workspace.py --image $env:CALIBURN_SANDBOX_TEST_IMAGE
docker build --tag caliburn-backend:m2 .
```

- Final suite: **97 passed, 3 skipped, 1 upstream TestClient warning**, no failures/errors, 42.44s. Skips are exactly SQLite instances of the three PostgreSQL-specific concurrency/immutability/idempotency/role checks; corresponding PostgreSQL cases passed. Real-container tests were enabled, not skipped. Intermediate targeted sandbox suites progressed from 24 to 35 to 39 passes as additional boundaries were implemented.
- Ruff check, format check (37 files), compileall: PASS. No dedicated mypy/pyright configuration/result is claimed.
- Actual Docker kernel/config evidence: UID 10001, CapEff=0, NoNewPrivs=1, Seccomp=2, only loopback interface, no Docker socket, root write denied/HostConfig read-only independently checked, memory=134217728 bytes, PID=32, CPU=50000/100000.
- Real PostgreSQL role test verifies SQLSTATE **42501** for runtime workspace-grant INSERT/UPDATE/DELETE after actual migration/default grants. Its temporary role/default privileges live in one rolled-back transaction within the test schema; no global role was left behind.
- Actual local Git 2.31 fixture imports immutable committed content despite working-tree replacement; a promisor configuration is denied. Official Git flag semantics are linked in M2_WORKSPACES.md. No Git binary/source was added to the agent/sandbox image and no remote was fetched.
- Final separate-process demo: API + fixture worker + trusted supervisor + per-request Docker containers, real HTTP/PostgreSQL/SSE; COMPLETED after **5 model calls / 4 tool calls** (list/search/read/patch), four sandbox completion events, exact candidate diff and source/image hashes. Evidence: `docs/evidence/m2-workspace-demo.json`. Inference is mocked; source operations, queue, diff, containers and transport are real. Candidate approved=false/executable=false; source_executed=false; no host/external repo changed.
- No managed task containers remained after success/timeout/cancel/revoke tests. The demo stops its own processes. The supervisor was not installed as a daemon or attached to API/worker containers.

Changed implementation: `src/caliburn/sandbox/` (typed contracts/manifests, frozen snapshots, queue, fixed data runner, trusted control plane, explicit directory/Git importer); runtime schema/contracts/store/worker/API; known-secret redaction and legacy guard; migration 0002 and supplied-connection migration tests; sandbox image Dockerfile; tests and shared isolated DB fixture; demo/model-fixture scripts and real-Docker CI opt-in; M2 runbook/ADR/plan/architecture/security/contracts/acceptance/current-status docs. No dependency or upstream UI branding changes were made.

Important remaining scope: actual task-local Git checkout, independently approved test execution and test-based repair, fixed real-repository benchmark, approval-gated external writes, real Open WebUI UI smoke/timeline, factory/registry, OIDC/broker, evaluated memory/routing, production isolation/cleanup qualification and customer SBOM/legal release gates. Local read/patch container checks do not qualify arbitrary candidate execution or establish Codex-level autonomy. The goal remains active; the next unit is the independent exact-digest execution approval boundary followed by actual sandboxed tests/repair, without enabling a model self-approval path.

Migration/rollback instructions are in M2_WORKSPACES.md and ADR 0002: additive tables/nullable column, preserve M1 data and old idempotency; stop/backup before upgrade; only explicitly approved destructive downgrade to 0001 and previous application version. Automated rollback was limited to isolated test schemas.

Final M2 addendum: invalid-source CLI validation is now sanitized so Pydantic/source snippets cannot be printed by the operator importer. The new confidentiality deny-path test passes. Latest complete suite: **98 passed, 3 SQLite-only PostgreSQL checks skipped, 1 upstream warning, 0 failures/errors**, 43.47s. Final Ruff/format/compile checks pass. Backend image build `caliburn-backend:m2` succeeds with the packaged workspace modules; its non-root import smoke confirms no Docker CLI/socket. No new runtime dependency, paid provider, external write or generated-source execution was enabled.

Cleanup: no managed task containers remained; the disposable caliburn-m2-postgres test container was stopped after verification. Existing M1 Compose volumes/containers and unrelated services were left untouched.

## Verified lifecycle correction and actual Open WebUI smoke — 2026-11-08

Previous continuation classification: progress (implemented/verified M2 data tools). Current inspection found a later-created legacy test container in Created state, PID=0, no host mounts, network=none and no current managed label. The earlier no-container observation was a point-in-time check, not proof against a delayed daemon create. The exact inspected test container was removed; no wildcard cleanup or unrelated service was touched. This evidence changed the next action: repair ownership/recovery before any candidate-execution expansion.

Implemented correction: shield/retain the entire Docker spawn-and-create handshake (including the pre-handle return interval), bounded creation/cleanup, late completion removal, managed-v2 expiry labels persisted before start and guarded startup/periodic reaping. Reaper preserves unexpired, malformed, foreign-named, legacy/unlabeled and host-data-bearing instances. It operates only with existing trusted host control-plane access; no agent Docker permission/socket/network grant is added. Restart or explicit reaper execution is required if the supervisor is stopped. ADR 0003 supersedes any stronger cleanup implication in earlier notes.

Actual lifecycle regression uses a maintained subprocess fixture that delays a real Docker create until cancellation has occurred before process-handle assignment. After completion, the target does not exist. Additional real Docker tests cover delayed timeout, persisted pre-start labels, fresh-controller reaping and preservation deny paths. None executes workspace source.

The remaining M1 UI smoke is now observed, not inferred from API shape: pinned Open WebUI 0.13.0 slim, unchanged branding, actual in-app browser interaction, selected caliburn-agent-durable, prompt `CALIBURN WebUI smoke: sum 17 25`, displayed result 42. Matching PostgreSQL record: task COMPLETED, 2 model calls, 1 tool call, events 1..9. Evidence: `docs/evidence/m1-openwebui.json` and `.png`. Inference is an offline fixture, not a real model. This does not check off enterprise principal/repository-grant acceptance, task timeline UX or licensing clearance.

Added a real consumer-compatible durable chat stream adapter: role/task-reference frame, final committed result, stop and DONE (bounded error frame after headers). Native task events remain separate SSE with authorized replay. This is completion-level OpenAI compatibility, not live provider token streaming. A separate real HTTP test closes after the initial frame, verifies a QUEUED task, starts a worker, then verifies COMPLETED and event replay; evidence: `docs/evidence/m1-chat-disconnect.json`.

Changed files: `src/caliburn/sandbox/control.py`, new `src/caliburn/chat_adapter.py`, gateway dispatch in `app.py`; lifecycle/chat transport tests and delayed-create subprocess fixture; actual disconnect and fixed loopback development transport scripts; pinned optional smoke Compose overlay; ADR 0003, smoke runbook, plan/current-state/security/contracts/evidence docs. No database migration, runtime dependency, candidate execution permission, upstream UI source/branding change or paid inference.

Commands/evidence:

- `docker run --detach --rm --name caliburn-m2-recovery-postgres --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=caliburn_test --publish 127.0.0.1:55432:5432 postgres:17-alpine`.
- With TEST DB URL and reviewed local `CALIBURN_SANDBOX_TEST_IMAGE`, `.venv/Scripts/python.exe -m pytest -q`: **109 passed, 3 skipped, 1 upstream TestClient warning, 0 failures/errors**, 53.40s. Three skips are SQLite instances of PostgreSQL-only checks; PostgreSQL/real-container cases ran. Targeted new chat tests: 6 passed; initial lifecycle set: 4 passed, then a real pre-handle process-gap regression was added and passed in the full suite.
- `.venv/Scripts/python.exe -m ruff check src tests migrations scripts`, `ruff format --check` and `compileall -q src migrations scripts`: PASS (43 Python files after the last test helper).
- `.venv/Scripts/python.exe -m alembic upgrade head` on disposable DB, then `scripts/demo_chat_disconnect.py`: PASS, actual socket disconnect leaves QUEUED, new worker completes, replay 2..9.
- `docker pull ghcr.io/open-webui/open-webui:v0.13.0-slim`: registry denied. Used the official documented Docker Hub mirror; `docker pull openwebui/open-webui:0.13.0-slim` succeeded, pinned digest `sha256:283efb20756785229a388bcd1e56a052f5284ae8c861717eed5eaaa3bba6b20a`. Exact tagged LICENSE reviewed and linked in OPEN_WEBUI_SMOKE.md; no credentials/bypass or branding modification.
- `docker compose -p caliburn-webui-verify -f compose.yaml -f compose.webui-smoke.yaml --profile webui-smoke up --build --detach`: PASS, new isolated owner/runtime DB roles and separate migrations, offline WebUI/fixture backend. Secret values generated only in process environment, not printed/persisted in evidence/source.
- Target Docker Desktop exposed no ports on the internal-only bridge despite HostConfig bindings. `scripts/webui_loopback.py --project caliburn-webui-verify` provided a fixed-target loopback-only operator Docker stdio transport; actual UI browser/HTTP/SSE/WebSocket worked without opening agent egress or adding a socket. This workaround is not production ingress.
- Actual browser result and matching DB/event record verified; test UI did not require account/password/permission changes or code execution. Third-party release notes dismissed as a nonbinding panel only.

Remaining goal scope is unchanged: product task timeline and verified enterprise identity; actual task-local Git checkout, independently approved candidate test execution and test-based repair/benchmarks; governed capability factory/registry; OIDC/Vault/broker; evaluated memory/skills/model routing; on-prem/customer operational/legal release gates. Approval/test execution implementation was deferred in this turn to fix an observed lifecycle boundary and close the original M1 UI proof gap; no weaker substitute is marked as fulfilling it. The overall goal remains active.

Migration/rollback: no schema changes in this correction. Previous adapter rollback reintroduces streaming 501; previous executor rollback reintroduces an observed cleanup defect. Preserve fixed cleanup/reaper capability and operator evidence. The WebUI smoke uses a new development DB/UI volume; stop only its named processes/containers and preserve volumes. Do not apply auth-disabled fixture mode or operator transport to customer data/production.

Cleanup completed: stopped only caliburn-webui-verify UI/API/worker/PostgreSQL containers, the disposable caliburn-m2-recovery-postgres fixture, and the loopback bridge whose listener PID/command line matched this test. Preserved all named WebUI/Compose volumes, original M1 containers/volumes and unrelated services. No managed-v2 sandboxes remained after final checks. Browser proof is saved as a local screenshot; no persistent service or execution approval was installed.

## M2.3a — Working independent candidate review — 2026-11-08

Previous continuation classification: progress (lifecycle correction and real WebUI proof). This unit implements a running policy consumer rather than declaring a placeholder approval state complete. Candidate source execution remains disabled throughout; approval tests use synthetic identities and do not constitute human approval.

Implemented:

- Patch result publication now atomically persists an immutable, task/step/workspace/actor/tenant-bound candidate and returns its server-generated reference. A runner cannot supply that reference. Stale controller/task leases cannot persist candidates.
- Six additive 0003 policy tables store candidates, bounded operator-owned inert test plans, reviewer mappings, review requests, decisions and revocations. PostgreSQL stamps author/reviewer roles and denies mutable evidence and direct runtime policy grants/decisions.
- Explicit request_review permission exposes a strict repo_request_review tool. It hashes task/actor/tenant/workspace/base/candidate/plan/image/tool implementation and enters actual WAITING_APPROVAL. Existing/default workspaces receive no review permission.
- Separate PostgreSQL role/current_user and mapped principal checks deny self-approval. Reviewer inspect/decide/revoke CLI is usable, with exact source/diff/test-plan JSON and expected digest. No approval HTTP endpoint, role/password provisioning, model approval flag or general resume bypass was added.
- Approve atomically requeues; reject terminates; revoke fences active work; decision expiry invalidates consumption; pending task deadline is swept. New worker resumes the stored call without repeating the patch or resetting budgets. Typed output explicitly says source_executed=false and sandbox_test_only.

Changed files: new `src/caliburn/policy/{schema,contracts,review,cli}.py` and package; `migrations/versions/0003_review.py`, migration metadata; workspace contracts/queue/import CLI; runtime store/worker/API; `tests/test_review.py` and runtime SQL privilege checks in `tests/test_sandbox.py`; ADR 0004, CANDIDATE_REVIEW runbook, architecture/contracts/acceptance/plan/README and verification JSON. No dependency, upstream branding or license assumption changed.

Exact validation commands (PowerShell, isolated fixture DB, no paid API):

```powershell
docker run -d --rm --name caliburn-review-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest tests/test_review.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations
.venv/Scripts/python.exe -m caliburn.policy.cli --help
docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'
docker exec caliburn-review-postgres psql -U postgres -d caliburn_test -Atc "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'review_fixture_%'"
```

Results: initial unchanged regression **109 passed / 3 skipped**, first review suite **7 passed / 7 skipped**, expanded targeted suite **10 passed / 9 skipped**, final full suite **118 passed / 11 skipped / 0 failures**, 77.53s. One existing upstream Starlette/httpx TestClient deprecation warning. Skips are the PostgreSQL-specific SQLite cases plus one PostgreSQL instance of a SQLite-only denial check; the real PostgreSQL/Docker/CLI approval-resume scenario passed. Ruff PASS, format PASS (75 files), compileall PASS. No separate mypy/pyright result is claimed. Actual data containers and role fixtures were cleaned: 0 managed-v2 containers, 0 random review_fixture roles observed after the suite. Evidence summary: `docs/evidence/candidate-review-verification.json`.

Not built: candidate/test execution, task-local checkout, test-based repair/benchmark, cryptographic signing/production activation, enterprise/OIDC approval identity or tenant-isolated review API. Test plan/image are inert reviewed artifacts; the current data runner does not execute them. Reviewer roles are trusted development DB principals, not customer-facing multi-tenant access. Production/operator superusers can change database policy; append-only records are not administrator-proof. No real reviewer was provisioned and no live candidate was self-approved.

Migration/rollback: 0003 is additive and preserves runtime/workspace data. Stop processes, backup and use owner connection to upgrade; no automatic downgrade. The contract change intentionally refuses existing workspace tasks with old pinned digests. Preserve review evidence on application rollback, reconcile waits explicitly; destructive downgrade to 0002 requires an approved maintenance/backup plan. Disposable-schema downgrade/re-upgrade passed in the SQL permission test. Detailed steps/limits: ADR 0004 and CANDIDATE_REVIEW.md.

Next priority: a separately qualified, fixed-image, bounded test executor that consumes exact approved candidate/plan/image hashes and rechecks grant/expiry/revocation/leases at dispatch and result publication, then actual failing-baseline/passing-candidate evidence and repair. That is a new execution boundary and is not marked done by review-only success. Enterprise promotion, external writes and privilege expansion remain separately authorized gates. The overall goal stays active.

## M2.3b — Actual independently reviewed stdlib tests — 2026-11-08

Previous continuation classification: progress (real independent review and resumed worker). This continuation implements and verifies the execution consumer; review-only status is no longer treated as a substitute for test evidence. No real user repository execution permission, live reviewer credential or production grant was enabled. All executable samples and reviewer identities in validation are explicit test fixtures.

Implemented:

- Strict repo_test input accepts only an approved request reference. Explicit operator execute_reviewed_tests permission requires patch+review grants; default/existing workspaces remain data-only. Model/client cannot choose source/plan/image/command/credentials or approve itself.
- The data supervisor filters out test jobs. A separate opt-in trusted-host test supervisor uses the same durable sandbox_jobs queue with lease/retry/budget/replay/cleanup behavior. No schema migration beyond 0003, new runtime dependency, agent Docker socket or host filesystem grant.
- Review binding v2 includes execution permission and driver/control/tool hashes. Full task/workspace/candidate/plan/image/independent review checks run at request, claim, heartbeat, polling, source-delivery admission, between variants and result publication. Wrong image, missing grant, stale controller, revoke/expiry and task cancellation deny execution/results.
- Fixed stdlib unittest driver executes the same independently registered plan against baseline/candidate in two fresh isolated containers. Source/tests arrive only on stdin into distinct tmpfs roots. No host candidate import, package install or model-selected shell. Actual process exit/hash/log evidence is stored and consumed by the worker; production_approved=false remains explicit.
- Existing Docker isolation is independently inspected, now including exact image ID: nonroot10001, network none, read-only root, no host mounts/socket, cap-drop/no-new-privileges/seccomp, memory128MiB/0.5CPU/PID32, tmpfs16MiB/noexec. Child environment omits platform configuration; 10-second wall/8 CPU seconds/1MiB file/16KiB output limits and parent/container cleanup bound execution. Python can interpret text on noexec tmpfs; noexec is not a code-execution prohibition.
- Interrupted checkpoint after durable sandbox completion reuses evidence with no supervisor/re-execution, charging the extra worker attempt. Active pause/cancel/revoke removes the actual running container and prevents candidate launch. Review inspection reports execution true only for committed evidence; dispatched/fenced attempts without it are null/unknown, never falsely called unexecuted.

Changed code: sandbox contracts/queue/control/importer, new test_control.py/test_runner.py/test_check.py and deploy/sandbox/Dockerfile.tests; policy authorization/binding/inspection and idempotent same-principal reviewer grant refresh; runtime task policy; shared reviewer fixture and new tests/test_reviewed_execution.py; CI builds/enables both real images. Docs: ADR 0005, REVIEWED_TESTS, current review/workspace/architecture/security/contracts/acceptance/plan/README and progress; actual execution JSON/JUnit evidence. No upstream branding, dependency license assumption, paid provider or external repository write changed.

Validation (exact PowerShell commands):

```powershell
docker build -f deploy/sandbox/Dockerfile.tests -t caliburn-sandbox:reviewed-tests .
docker run -d --rm --name caliburn-execution-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
$env:CALIBURN_EXECUTION_EVIDENCE='docs/evidence/m2-reviewed-tests.json'
.venv/Scripts/python.exe -m pytest tests/test_reviewed_execution.py -q -x
.venv/Scripts/python.exe -m pytest tests/test_review.py tests/test_reviewed_execution.py -q -x
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m2-reviewed-tests-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations
.venv/Scripts/python.exe -m caliburn.sandbox.test_control --help
docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'
docker exec caliburn-execution-postgres psql -U postgres -d caliburn_test -Atc "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'review_fixture_%'"
docker stop caliburn-execution-postgres
```

Results: initial execution tests **9 passed / 6 skipped**. An expanded regression exposed reviewer inspection lacking sandbox_jobs SELECT; corrected with an explicit operator-owned, idempotent mapping refresh, not broader agent privileges. No live reviewer was modified. Corrected review/execution suite **24 passed / 17 skipped**. First full regression **133 passed / 20 skipped / 0 failures**, 136.37s. Added injected checkpoint interruption; final full regression **134 passed / 21 skipped / 0 failures**, 143.55s. All skips are unsupported SQLite instances of PostgreSQL-authority/concurrency/ACL checks plus one PostgreSQL instance of the SQLite-only denial test; real PostgreSQL and Docker execution tests ran. One existing upstream Starlette/httpx TestClient deprecation warning. Ruff PASS; format PASS (81 files); compileall PASS; no mypy/pyright claim.

Actual recorded scenario: task COMPLETED, 4 fixture model calls/3 tool calls, baseline FAILED/exit1, candidate PASSED/exit0, same independent test-plan hash and exact pinned image `sha256:3d891106e0b144981d8aef22177db91105adedcf874d769430ae4a78fd86e6fa`. Normal execution JSON: docs/evidence/m2-reviewed-tests.json; final test inventory/results: docs/evidence/m2-reviewed-tests-pytest.xml. Injected recovery variant completes with 4 model calls/4 charged tool attempts and no second supervisor. Fixture data is not a live-model quality score, real human approval, malicious-code safety certification or registry promotion.

Remaining scope: iterative failed-candidate repair with a new independent review per changed hash, actual per-task Git checkout, fixed real-repository/live-model benchmark, production sandbox/rootless/user-namespace/microVM/supply-chain qualification, signed factory/registry, enterprise OIDC/tenant reviewer service, credential broker, evaluated memory/skills/routing and customer operational/legal release gates. Full M2 and the overall goal remain active, not complete.

Migration/rollback: no new schema change. Driver/tool/control/binding-v2 changes intentionally invalidate old pinned workspace tasks/approvals; create new explicitly granted tasks and independent decisions. Do not silently repin. Existing reviewer sandbox_jobs read access requires a separately authorized operator mapping refresh. Stop both supervisors/workers, revoke explicit execution grant or cancel tasks, preserve review/job/evidence data and restore preceding data-only code; no DB downgrade is needed. Detailed limits and the authorization-transaction/dispatch race are in ADR 0005/REVIEWED_TESTS.md. No production enablement or deployment was performed.

Cleanup verified after final regression: 0 managed-v2 sandbox containers, 0 temporary reviewer roles; stopped only the disposable caliburn-execution-postgres test container. Existing Compose/WebUI volumes and unrelated services were preserved. Final Ruff/format/compile checks remained green after documentation updates.

## M2.4a — Actual failure → parent repair → fresh approval → retest — 2026-11-08

Previous continuation classification: progress (real independently reviewed test execution and checkpoint reuse). Current inspection confirmed repo_patch always used the original snapshot, so iterative fixes could not inherit a complete earlier candidate or expose an immutable parent relation. This unit implements the missing consumer and verifies actual repair behavior, without treating fixture inference as real-model coding quality.

Implemented:

- Optional strict parent_candidate_ref selects a server-resolved same-task/workspace/actor/tenant candidate as patch source. Original behavior is preserved when omitted/null. Source bundle/base hashes and bounded ancestry are validated; no model-provided parent files/host paths or authority are accepted. The data runner receives only resolved source and performs an inert patch.
- Additive migration 0004_candidate_parent stores nullable self-FK parent_id, preserves existing roots and rejects cross-scope PostgreSQL INSERTs. Parent links inherit existing append-only evidence rules. Up to 32 candidates per chain; cycles/missing/mismatched/deep parents fail closed. Full child bundles retain prior changes in other files.
- Binding v3 includes parent reference and patch-source bundle hash. Modified children never inherit parent approval: each creates a new WAITING_APPROVAL, exact digest and independent decision. Original workspace remains the comparison baseline.
- Existing durable worker now has a tested running consumer for actual failed-test observation → parent-based repair → second approval → retest. Cumulative model/tool/token/time budgets remain in force across both waits. Rejection and a 4-tool ceiling stop before a second comparison.

Changes: sandbox contracts/runner/queue, policy candidate schema/source resolution/publication/binding, new migration 0004; tests/test_repair_loop.py and tests/test_candidate_ancestry.py; rebuilt fixed data/test images; ADR 0006, REPAIR_LOOP.md, plan/architecture/security/contracts/acceptance/README/progress and actual evidence JSON/JUnit. No dependency, credential, external write, existing execution grant or upstream branding/license assumption changed.

Exact validation commands (PowerShell, existing Python3.12 venv, isolated schemas/fixture identities):

```powershell
docker build -f deploy/sandbox/Dockerfile -t caliburn-sandbox:m2 .
docker build -f deploy/sandbox/Dockerfile.tests -t caliburn-sandbox:reviewed-tests .
docker run -d --rm --name caliburn-repair-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
$env:CALIBURN_REPAIR_EVIDENCE='docs/evidence/m2-repair-loop.json'
.venv/Scripts/python.exe -m pytest tests/test_review.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x
.venv/Scripts/python.exe -m pytest tests/test_repair_loop.py -q -x
.venv/Scripts/python.exe -m pytest tests/test_candidate_ancestry.py -q -x
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m2-repair-loop-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations
docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'
docker exec caliburn-repair-postgres psql -U postgres -d caliburn_test -Atc "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'review_fixture_%'"
docker stop caliburn-repair-postgres
```

Results: review/SQL regression **10 passed / 9 skipped**; actual repair/second-rejection/budget suite **3 passed / 3 skipped**; ancestry first **4 passed**, with populated-migration coverage **6 passed**. Final complete suite **143 passed / 24 skipped / 0 failures**, 182.64s. Skips are the PostgreSQL-only SQLite cases plus the one PostgreSQL instance of the SQLite-only denial test; real PostgreSQL and both actual Docker images ran. One existing upstream Starlette/httpx TestClient deprecation warning. Ruff PASS, format PASS (86 files), compileall PASS; no mypy/pyright result claimed.

Actual repair evidence: 7 fixture model calls/6 tool calls, task COMPLETED; first baseline FAILED and first candidate FAILED (assertion 6 != 5); child source bound to first candidate; after a distinct second independent-role fixture decision, original baseline FAILED and child PASSED. Two candidates/two review requests/two actual baseline-candidate comparisons. In second-review REJECT or cumulative tool-ceiling scenarios, final error review_rejected/tool_call_limit, 5 model calls/4 tool calls and exactly one comparison; token reservations never reset. Evidence: docs/evidence/m2-repair-loop.json, final inventory docs/evidence/m2-repair-loop-pytest.xml. No live model, real human approval or external repository was involved.

Pinned rebuilt images: data `sha256:f293e27677d6ebd5c7d2727eaa37467f34d03dcd45a8d4f5cf6bb87a759a0b01`; reviewed tests `sha256:82aa8469878c761db32e2623be3496196b18f67eb179c2570af8c79813438c89`. Historical images/evidence were not pruned or repinned. These are local operator-reviewed fixture build IDs, not signed customer release artifacts.

Migration/rollback: 0004 adds a nullable parent self-reference and PostgreSQL scope trigger; populated 0003 root preservation and upgrade are verified on both dialects. Stop consumers, backup/restore-check and use owner-only upgrade before the new code; runtime privileges remain unchanged. Old pinned task/tool/runner/approval hashes intentionally refuse changed implementations; rebuild both images and obtain new task/review references rather than silent repinning. Preferred rollback preserves 0004 plus all lineage/review/job evidence and deploys compatible preceding code after stopping dispatch/reconciling tasks. Destructive downgrade loses ancestry and requires separate approved maintenance/backup; only disposable schemas were downgraded in tests.

Remaining: actual per-task Git checkout, fixed real-repository/live-model benchmark and failure taxonomy, production sandbox/supply-chain qualification, signed capability factory/registry, enterprise OIDC/tenant reviewer identity, broker, evaluated memory/skills/routing and customer operations/legal release. The fixture repair mechanism is implemented; full M2, Codex-level coding quality and the overall goal are not complete. Next priority is task-local checkout and a reproducible real-repository benchmark foundation, retaining explicit execution/review gates.

Final cleanup: 0 managed-v2 sandbox containers and 0 temporary reviewer roles observed; stopped only caliburn-repair-postgres. Preserved prior named Compose/WebUI volumes, historical images and unrelated services. Final Ruff/format/compile checks remain green. No production migration, reviewer provisioning, real repository execution grant or external write was performed.

## M2.1a — Actual scoped operator Git checkout/handoff — 2026-11-08

Previous continuation classification: progress (actual iterative failure/repair/fresh review/retest). Inspection confirmed current repository ACL is a file-list snapshot grant, not permission to clone undisclosed original history. This unit implements a concrete operator checkout/handoff consumer without widening that authority or presenting a reconstruction as an original-history clone. Agent-contained Git checkout remains explicitly incomplete.

Implemented: operator-only `python -m caliburn.sandbox.checkout` reads actual scoped task/workspace/candidate data, validates active read/TTL/actor/tenant/hash/ancestry and materializes a fresh private task repository. Existing operator Git creates bounded blob/index/tree objects, a deterministic derived baseline commit and an actual detached checkout. Candidate bytes are staged via index objects and actual Git emits the patch. Original source commit is separate provenance; no original repository/history/remotes or excluded files are copied. Typed CheckoutReport records source and Git/patch identities with source_executed=false/production_approved=false. Replays create independent directories with identical identities, and publication rechecks read authority.

Security: fixed no-shell command sequence; isolated Git environment/global/system configuration, empty template/hooks path, disabled fsmonitor/credentials/protocols/automatic maintenance, no filters/external diff/textconv and highest-precedence byte-preserving attributes. No source import/execution, agent host-process route, Docker permission or new redistributed Git binary. In-flight deny/cancel/timeout removes only the verified fresh output tree. Initial revoke test found actual Windows Git object readonly permissions prevented cleanup; fixed with a guarded within-owned-tree readonly retry. No original checkout or existing output was deleted. Existing worker/tool/policy code/digests and 0004 schema remain unchanged.

Changed files: new sandbox/checkout.py, tests/test_task_checkout.py; maintained demo_workspace output/return/candidate-reference support plus scripts/demo_task_checkout.py; CI handoff demo step; ADR 0007/TASK_CHECKOUT and plan/architecture/security/contracts/acceptance/README/progress; JSON/JUnit evidence. No dependency license, Open WebUI branding, production grant, paid API or external repository write changed.

Exact observed commands (PowerShell; synthetic fixture DB/token):

```powershell
git --version
git update-index -h
docker run -d --rm --name caliburn-checkout-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest tests/test_task_checkout.py -q -x
$env:CALIBURN_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_API_TOKEN='checkout-demo-fixture-service-token'
$env:CALIBURN_PROVIDER='fixture'
.venv/Scripts/python.exe -m alembic upgrade head
$image=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
.venv/Scripts/python.exe scripts/demo_task_checkout.py --image $image
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m2-task-checkout-pytest.xml
.venv/Scripts/python.exe -m pytest tests/test_task_checkout.py -q
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'
docker exec caliburn-checkout-postgres psql -U postgres -d caliburn_test -Atc "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'review_fixture_%'"
docker stop caliburn-checkout-postgres
```

Results: initial checkout test exposed Windows readonly cleanup failure (**7 passed / 1 failed**, corrected); corrected suite **16 passed**, 26.47s. Added principal/tenant/output-root and CLI confidentiality cases: final checkout-only **20 passed**, 34.66s. Full regression (collected before those four additional cases) **159 passed / 24 skipped / 0 failures**, 209.84s; the four new cases are covered by the 20-case target run, not falsely counted in the full XML. PostgreSQL/Docker cases ran; skips remain PostgreSQL-only SQLite instances plus the one PostgreSQL SQLite-denial instance. One existing upstream TestClient deprecation warning. Ruff/format/compile PASS (93 files at final check), no separate mypy/pyright claim.

Actual separate-process demo: HTTP/SSE API + scripted fixture worker + trusted supervisor/per-request Docker data containers create task c79ab31f-4761-4095-8cc4-c8af91d88805 (COMPLETED,5 model/4 tool calls, list/search/read/patch). Separate operator CLI exports candidate ecf117fb-63a7-4edf-8caf-c4586144b923. Retained fixture package `.caliburn/checkouts/caliburn-task-lu7iw3a2/` contains repo/,manifest.json,candidate.patch. Independent post-export Git checks verify HEAD `98b589844067d2bdeafe68e3217d2923891068a3`, candidate index tree `2901c0f08056706a643ff963f3b72374280953af` and staged patch SHA256 `daeb13186f1751c9e895bc2082a9edc639e0a4c2c91e8f68630d3d2d13e34982`. All source/inference are fixtures and no source executes or receives approval. Host Git observed:2.31.0.windows.1. Evidence: m2-checkout-source-task.json,m2-task-checkout-demo.json,m2-task-checkout-pytest.xml.

Migration/rollback: no schema migration (head0004), no task repinning or worker restart needed for this operator component. Remove/disable the CLI to roll back; preserve task/evidence data and operator packages. Each output is a bounded scoped data copy whose retention is operator-controlled; later grant revocation cannot retract exported copies. Failed cleanup is limited to the exact verified generated subtree, never an arbitrary supplied root. No customer DB was changed; only the disposable fixture DB was migrated.

Not built: model/agent Git execution, original-history clone/checkout, fixed real-repository/live-model benchmark, PR/push/external-write consumer, production Git/sandbox/dependency qualification, factory/registry, enterprise identity/broker, evaluated memory/routing and customer operational/legal release. This unit is a real operator handoff, not full M2 or a replacement for the original goal. Next safe priorities are qualified agent Git integration and fixed-repository benchmark preparation without granting host shell or assuming redistribution rights.

Final cleanup verified: 0 managed-v2 sandboxes and 0 temporary reviewer roles; stopped only caliburn-checkout-postgres, while the completed fixture review package is deliberately retained. Checked/removed only the exact observed initial failed-test partial output through the guarded native cleanup helper. Original Compose/WebUI volumes, historical images and unrelated services were preserved. No production grant, original checkout, upstream branding, external repository or user source was modified. Final Ruff/format/compile remained green.

## M2.1b — Fixed Git data boundary prepared; image qualification awaits approval — 2026-11-08

Previous continuation classification: progress (actual operator checkout/handoff). This unit implements the separate runtime consumer and keeps the new Git binary/dependency build behind the user's explicit license-risk approval requirement. It does not substitute host transport fixtures for container qualification or mark agent Git complete.

Implemented code: repo_git_status strict candidate-reference-only contract and typed bounded GitData; operator-only git_inspect permission with immutable image pinned in workspace provenance/task policy; same-task/source/tenant/ancestry/hash/image/lease checks on enqueue/claim/heartbeat/result; default/data/test consumer exclusion; separate GitDockerExecutor with live source-delivery admission and runner/source attestations. The shared stdlib Git workspace performs actual checkout/index/diff using fixed commands without importing source, hooks/filters/network/external diff. Existing operator checkout now consumes that same shared implementation and remains regression-tested. Existing/default grants gain no permission.

Concrete review files: new sandbox/git_workspace.py, git_runner.py, git_control.py and deploy/sandbox/Dockerfile.git; contracts/queue/importer/task-policy integration; checkout shared extraction; tests/test_git_boundary.py; pyproject Ruff excludes ignored .caliburn generated review copies; deterministic heartbeat boundary test correction; ADR0008/GIT_DATA_APPROVAL plus plan/architecture/contracts/acceptance/licensing/README/progress. No schema migration (head0004). Changed workspace implementation digests intentionally refuse old pinned tasks/reviews instead of repinning. No live Git grant, Git package install, new Git image, customer deployment, source execution or remote repository write was enabled.

Proposal: development-only Docker Git image based on python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b; observed OS Debian13/trixie. Proposed Git package 1:2.47.3-0+deb13u1 from official Debian package listing, with --no-install-recommends required dependencies. Build defaults blocked unless CALIBURN_ALLOW_GIT_DEV_IMAGE=true. It records dpkg inventory and retains Git copyright; exact transitive package versions remain unobserved until an approved build. Git upstream COPYING identifies GPLv2; this newly binary-containing image requires explicit review and is not customer distribution/legal/SBOM clearance. Primary sources: https://packages.debian.org/trixie/git and https://raw.githubusercontent.com/git/git/master/COPYING. User approval for the exact development build/local fixture qualification was requested through the asynchronous input tool; no answer/approval has been received in this turn.

Executed validation commands (PowerShell, existing host Git and isolated fixture PostgreSQL):

```powershell
docker run -d --rm --name caliburn-git-boundary-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest tests/test_task_checkout.py -q -x
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest tests/test_git_boundary.py -q
.venv/Scripts/python.exe -m pytest tests/test_runtime.py::test_heartbeat_prevents_double_claim_and_deadline_survives_pause -q
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m2-git-boundary-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
docker image ls --format '{{.Repository}}:{{.Tag}}' --filter reference='caliburn-sandbox:git-dev'
docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'
docker exec caliburn-git-boundary-postgres psql -U postgres -d caliburn_test -Atc "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'review_fixture_%'"
docker stop caliburn-git-boundary-postgres
```

Results: shared operator checkout **20 passed**,33.55s. Git boundary **11 passed / 2 skipped**,12.57s; with additional actual-image kernel/attribute/timeout/cancel checks written but gated, **11 passed / 4 skipped**,15.57s. These passes use actual DB/worker/Git plus explicitly labeled fixture Docker transport; actual Git image cases were not run. The existing data Docker runner was real and no paid model was used.

First full run: **173 passed / 26 skipped / 1 failed**,229.28s. Failure was an existing heartbeat test assuming a second PostgreSQL call could occur within a real 50ms lease. Runtime correctly raised LostLease after expiry. Replaced only that timing assumption with a controlled per-store clock, advancing beyond the original lease after heartbeat and then beyond the preserved deadline; actual SQL transactions remain in use and other real-clock/process timeout tests remain unchanged. A new assertion initially read an internal deadline from the public API projection; corrected to the claimed task snapshot. Canceled the exact verified owned follow-on pytest process containing that known test assertion error, observed its terminal handle, corrected and reran the target: **2 passed**. No production lease rule was weakened.

Final full suite: **174 passed / 28 skipped / 0 failures**,225.93s, one existing upstream TestClient deprecation warning. Four skips are explicitly pending Git-image/container qualification; remaining 24 are existing unsupported SQLite PostgreSQL-authority/concurrency/ACL instances plus the PostgreSQL instance of the SQLite-only denial test. Final JUnit: docs/evidence/m2-git-boundary-pytest.xml. Ruff/format/compile PASS (97 files after excluding generated .caliburn review copies); no mypy/pyright result claimed. Docker image inventory confirms caliburn-sandbox:git-dev is absent. No actual Git-container success or production qualification is claimed.

Migration/rollback: no new schema; JSON permission/image fields default absent. Existing operator data export behavior stays usable; runtime workspace digests change and require explicit new task/review references. Stop/disable Git consumer and revoke explicit grants to roll back, preserving all DB/evidence; do not drop tables or bypass digest checks. The new image build is a separate approval action with exact command/proposal in GIT_DATA_APPROVAL.md; no approval is inferred from elapsed time or the input tool accepting the question.

Remaining for this unit: user-authorized development Git image build, actual installed package/license inventory, real Git container kernel/attribute/timeout/cancel/worker tests and failure analysis. Original-history clone, real-repository/live-model benchmark and all later enterprise factory/identity/broker/memory/routing/customer release gates remain open. Overall goal remains active; this is progress, not completion or a whole-project blocked declaration.

Final cleanup: no managed-v2 task containers. One temporary reviewer role from the canceled fixture run remained inside the disposable test cluster before shutdown; stopping/removing only caliburn-git-boundary-postgres discarded that isolated cluster, rather than altering roles in any persistent server. Container inventory confirms it is absent. Existing Compose/WebUI volumes, historical images and unrelated services were preserved; no Git dev image/build/grant was enabled. Final static checks remain green.

## M1 UI closure — actual task timeline/control/reconnect — 2026-11-08

Previous continuation classification: progress (prepared Git boundary and validated host-Git path). Git development image build approval has not been received; that step remains untouched. Continued an independently authorized missing M1 requirement: a real task timeline UI consuming existing runtime data and controls. This does not redefine full platform completion around UI success.

Implemented:

- Original independent caliburn.web console at /tasks/ui, with exactly allowlisted self-hosted HTML/CSS/two modules, strict CSP/no-store/nosniff/referrer headers and packaged wheel assets. No Open WebUI source/branding modification, UI framework/CDN or new runtime dependency.
- Authenticated paginated /api/v1/tasks/{id}/history: typed Run/Step/budget/deadline/hash projections, bounded ordinal/offset/limit, server-owned principal/tenant scope, no raw step model/tool input/output or task lease, known configured credential-bearing metadata denial. Reads neither claim work nor mutate state and do not take a worker lease.
- Actual state/result/budget/run/step/review/event views; existing pause/resume/cancel actions only. WAITING_APPROVAL has disabled resume and no approval action. Terminal pending reviews display undecided/ended instead of implying an actionable wait.
- Memory-only bearer session with cleared password field, same-origin no-store/no-cookie/no-redirect fetch, no browser storage or URL token, abort/drop credential on disconnect/page hide. All dynamic content uses literal textContent. Bounded UTF8/SSE framing, task/sequence/type identity and contiguous cursor, duplicate/gap denial, Last-Event-ID automatic retry/backoff and recent250-event display. Manual reload/new session replays from zero instead of persisting secrets/cursors.

Changed files: new web package/assets, app route mount, runtime history contracts/store/API, pyproject asset packaging/build-output exclusions, tests/test_timeline.py and timeline_stream.test.mjs, scripts/demo_timeline.py and CI Node protocol check; ADR0009/TASK_CONSOLE plus architecture/security/contracts/acceptance/plan/M1 runbook/README/progress/evidence. Existing worker/model/sandbox/candidate permissions remain unchanged; no schema migration (head0004).

Actual browser evidence (frontend-design skill; supported CUA browser API): main Task cb0f64da-a0c8-43e0-813b-75e0eec3114c was connected while QUEUED, paused via browser, survived API process restart with visible cursor2 and no duplicate events, resumed via browser, and completed through a separate actual fixture worker. Result42,2 fixture model calls/1 tool call,3 completed Steps,1 Run and11 unique events. DOM confirmed empty token field and zero injected img/script elements. Additional browser checks verified wrong-token denial, queued task f538c74e-d900-4dfe-bfe6-1b46e296da4f cancellation, independent-review task ddc19b7c-1f32-4932-a61f-cc32f69591a0 with disabled resume/cancellation, canceled pending-review label, and literal HTML/script result for 0d1b7029-33f7-46fb-9f2b-ed4ace266900 with no executable elements. The review fixture created only inert source/plan/pending request, never an approval or source execution.

Responsive check: requested390x844 browser viewport, observed content/client widths375/375 (scrollbar), no horizontal overflow; temporary override reset. Final UI source was reloaded and actual completed result/11-event state reverified after changes. Browser screenshots: docs/evidence/m1-timeline-browser.jpg (completed-task proof), m1-timeline-mobile.jpg, m1-timeline-review.jpg and m1-timeline-literal-result.jpg. Matching PostgreSQL histories: m1-timeline-browser.json and m1-timeline-controls.json. They contain synthetic fixture identity/model/source data; browser/HTTP/SSE/DB/API/worker are real. This is not live-model quality or enterprise auth proof.

Exact observed validation commands (PowerShell):

```powershell
node --version
node --check src/caliburn/web/assets/timeline.mjs
node --check src/caliburn/web/assets/stream.mjs
node --test tests/timeline_stream.test.mjs
docker run -d --rm --name caliburn-timeline-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
docker exec caliburn-timeline-postgres pg_isready -U postgres -d caliburn_test
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest tests/test_timeline.py -q -x
$env:CALIBURN_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_API_TOKEN='timeline-demo-fixture-token'
$env:CALIBURN_PROVIDER='fixture'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/demo_timeline.py
# In the maintained interactive fixture: restart, run, new, approval, xss, evidence, audit, stop.
# A continued fixture session used:
.venv/Scripts/python.exe scripts/demo_timeline.py --task cb0f64da-a0c8-43e0-813b-75e0eec3114c
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m1-timeline-pytest.xml
uv build --wheel --offline --out-dir .caliburn/package-check
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'
docker exec caliburn-timeline-postgres psql -U postgres -d caliburn_test -Atc "SELECT count(*) FROM pg_roles WHERE rolname LIKE 'review_fixture_%'"
docker stop caliburn-timeline-postgres
```

Results: first PostgreSQL fixture attempt raced container startup (2 SQLite/static cases passed,1 setup error); verified the same live container with pg_isready and reran, not restarted. Timeline suite initially5 passed, then **7 passed** after known-credential negative checks. Node built-in protocol suite **3 passed**, including split UTF8/CRLF/comments/multiline, duplicate/gap/wrong-task/frame-size and approval-control semantics. Full final Python suite **181 passed / 28 skipped / 0 failures**,230.25s,1 existing upstream TestClient deprecation warning. Four skips remain the unapproved Git-container build checks; other24 are existing DB-specific applicability cases. Actual approved-source test/data Docker cases ran; Git image was not built or enabled.

Packaging: venv has no pip module; used already installed uv with offline cached declared build dependencies. Actual wheel builds successfully and ZIP inspection verifies all4 console assets. Ruff/format/compile and JS syntax PASS; final format reports103 Python files, no separate mypy/pyright claim. CI gains the Node protocol command, but no remote CI run/push is claimed. Rendered UI content remained literal in the browser; no test token was embedded in assets/URLs/evidence or forwarded to a model.

Migration/rollback: additive API/assets only, no schema/digest/identity grant change. Keep head0004 and all task/event/review evidence. Restore prior application/asset version to remove console/history; no DB downgrade needed. Current console is an independent development UI requiring existing Task ID/service identity. Embedded Open WebUI navigation, OIDC/individual sessions, customer TLS/device/scale qualification, Git image approval/qualification, original-history/real-repository/live-model benchmark and later factory/registry/broker/memory/routing/customer release gates remain open. Overall goal stays active.

Cleanup verified: both interactive fixture API helpers/children were stopped via their own stop/finally path; no managed sandbox containers and0 temporary reviewer roles remained. Stopped only caliburn-timeline-postgres, preserving prior Compose/WebUI volumes, historical images, operator review package and unrelated services. No persistent/public UI service, Git package/image, real credential grant, external write or customer deployment was installed.


## M3.1a — durable quarantined proposal consumer (2026-11-08)

Prior continuation delivered the actual task timeline. The requested Git-containing Docker image remains unbuilt and unqualified: the prior development build/license-risk approval question has no user answer. Automatic goal continuation does not authorize it. Safe independent Factory proposal work proceeded; no Git image/grant or source-execution permission was added.

Plan/impact: implement exact-name capability lookup, typed inert bundle proposal, immutable PostgreSQL persistence and worker recovery, plus authenticated read inspection. New tool_factory package; runtime/config/API/chat wiring; additive migration0005; tests/evidence and ADR0010/runbook. No new library, upstream branding, license assumption, paid model, network write or installed generated code. Existing task policies retain their permissions. Feature is default-off and server-only; Compose/example expose the false default.

Implemented: bounded closed JSON input/output contracts and fixture shape checks; safe nonoverlapping source/test files; Python syntax metadata; tool/MCP/skill artifact kinds; declared exact dependency/SBOM/license and requested permission/handle metadata; canonical bundle digest; origin Task/Step/actor/tenant/DB-role provenance; same-version conflict and concurrent insertion resolution; immutable tables with PostgreSQL scope/mutation triggers and runtime-role restrictions. Generated tests, dependencies, permissions and license are unverified declarations. No candidate source executes, no skill instructions are adopted, no dependencies install, no MCP server starts.

Worker consumer: explicitly permitted new tasks advertise lookup/propose, pin digest and retain ordinary budgets. Proposal+receipt+hash/reference event commit atomically. Replay after a committed proposal but before checkpoint returns one candidate/event. Separate tasks inspect/reference the same quarantined version, but candidate names never enter executable definitions. GET /api/v1/capabilities/{id} uses existing fixed development bearer identity; no activation/approval/invocation endpoint. Known configured secret values are denied before persistence/output; this is not universal secret scanning or a real credential broker.

Validation in progress ledger: initial Factory tests26passed/2skipped, then process-death tests28passed/2skipped. Expanded final focused suite (Factory + existing PostgreSQL runtime-role migration test)35passed/3skipped,23.94s. First full regression207passed/30skipped/0failed,255.94s; final expanded full run pending below. The first attempted focused selector named a nonexistent test and collected no tests; corrected to test_migration_blocks_runtime_self_grant_in_postgres. Existing TestClient upstream deprecation warning remains. Ruff/format/compile, Node3 protocol tests and docker compose config --quiet pass. Formatter checks113 Python files. These are local checks, not remote CI.

Evidence: actual child process exits73 immediately after Factory proposal DB commit, before tool checkpoint. Parent explicitly expires its fixture lease; a separate Worker recovers the same Step and completes with1 bundle/1 receipt/1 CAPABILITY_QUARANTINED event and2 charged tool attempts. This tests an actual OS process death plus controlled lease expiry, not natural30second waiting or live inference. A source payload would create a marker if imported, but marker stays absent. Untrusted Skill instructions and invalid Python remain inert; direct invocation fails tool_policy_denied. Models/reviewer identities remain scripted/synthetic; PostgreSQL, worker/API stack, migration/immutability/contention and existing qualified Docker test paths are real.

Exact commands (PowerShell):
```powershell
docker run -d --rm --name caliburn-factory-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
docker exec caliburn-factory-postgres pg_isready -U postgres -d caliburn_test
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest tests/test_factory.py -q -x
.venv/Scripts/python.exe -m pytest tests/test_factory.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x --junitxml=docs/evidence/m3-factory-focused.xml
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m3-factory-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
node --test tests/timeline_stream.test.mjs
$env:CALIBURN_DB_ADMIN_PASSWORD='compose-fixture-admin'
$env:CALIBURN_DB_PASSWORD='compose-fixture-runtime'
$env:CALIBURN_API_TOKEN='compose-fixture-service'
docker compose config --quiet
```

Migration/rollback:0005 adds only factory tables/triggers. Durable test fixtures migrate from0001 through head and rollback0005 to0004/re-upgrade in private disposable schemas. No existing deployment DB was migrated. Prefer app rollback retaining evidence; disable the feature for new tasks and stop/cancel existing granted tasks. Explicit backed-up downgrade to0004 deletes Factory evidence and needs operator approval. Full lifecycle/gap-quality/qualification/independent reviewer/signing/active registry/qualified invocation reuse remain open. Next safe unit: define and implement independent Factory qualification evidence/admission without inferring authority from declarations or extending existing repository approvals. M4 identity/broker and M5 memory/routing/customer release remain unbuilt. Overall goal remains active.

Packaging: `uv build --wheel --offline --out-dir .caliburn/package-check` passed; ZIP inspection confirmed all5 new tool_factory modules in the actual wheel, together with existing console assets. No package was installed into a service/customer environment.


Final expanded verification: **215 passed / 30 skipped / 0 failures**,261.56s;1 existing upstream TestClient deprecation warning. Final JUnit: docs/evidence/m3-factory-pytest.xml. Four skipped tests remain unapproved Git-image qualification;26 are DB-specific applicability skips. Actual PostgreSQL and previously approved data/test Docker paths ran; no Git image was built. Expanded focused evidence remains35passed/3skipped in m3-factory-focused.xml; the final full suite also covers the last catalog/output-contract consumption change. Static checks and Node3 tests pass; wheel/Compose checks pass.

Cleanup: `docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'` returned no containers; reviewer-role count was0. `docker stop caliburn-factory-postgres` stopped/removed only this disposable --rm test database. Existing images, prior deployment volumes/operator review package and unrelated services were preserved. No persistent/public service or newly approved capability remains running. Goal remains active; M3.1a is done, full M3 and enterprise objectives are not.


## M3.2a — independent static triage consumer (2026-11-08)

Previous goal turn classification: progress, verified215passed/30skipped and shipped durable quarantine proposal/lookup/recovery. Current state was inspected before implementation. The separate Git-image development/license-risk approval still has no answer; no Git image build/grant or generated-source execution occurred.

Plan/impact: separate default-off capability_check, persisted static request/evidence, independently configured verifier DB role/process and runtime/API consumers; migration0006, no new runtime library/image/license/branding assumptions. Full source execution, behavior qualification and activation remain explicit later requirements, not redefined as static success.

Implemented: factory_check_jobs (Step-idempotent immutable input/scope/deadline/bundle/checker digests, SKIP LOCKED lease/fencing/max3 claims), factory_check_reports (atomic report+finished job, immutable hash/body/actual DB author) and owner-only factory_verifiers mapping. New checker/authority/verifier code plus input/output contracts; actual Worker async waiting/heartbeat/call timeout, separate task grant, filtered model-visible definitions and authenticated scoped report inspection. Unrelated-task same-scope candidate references may be checked; cross-scope/ref/step mismatch denied. Job input/terminal transitions and bounded monotonic attempts are DB guarded. Runtime cannot write reports/jobs/mappings beyond its immutable request insertion. Separate verifier cannot mutate Tasks/candidates, configure itself or attest its own source/request; permission expansion into runtime writes invalidates authority. Independent repository reviewer mappings grant no Factory verifier access.

Static analyzer validates bounded bundle/fixture shapes, AST parses Python and records bounded code/path/line triage: selected sensitive imports, dynamic/IO calls, dunder introspection, invalid syntax, limited English instruction-override patterns and permission/dependency review requirements. No candidate source/test/fixture behavior/MCP/skill executes; no dependency is installed. Unflagged results are REVIEW_REQUIRED, never PASS; all reports require source_executed=false, execution NOT_RUN, security INCOMPLETE, dependencies UNVERIFIED, license UNREVIEWED, activation_eligible=false. SQL rejects forged stronger claims. This is incomplete heuristic triage, not full SAST/injection/secret/dependency/license certification. Source stays QUARANTINED; old proposal checks are immutable historical data.

Actual new evidence: separate Python verifier OS process using synthetic independent PostgreSQL NOLOGIN role serves a queued capability_check while the runtime worker waits, then the runtime consumes the immutable report and completes. Separate-role rights, report API/auth/scope, stale verifier expiry/recovery, request checkpoint replay, cancellation/pause/deadline/offboarding, revision/retry/tool/call budget denials, concurrency and paused queue nonstarvation were exercised. Verifier crash recovery is simulated by expiring an actual lease; the separate process test is normal exit, not a new OS-crash test (proposal-process crash proof remains in test_factory). No production human reviewer/OIDC, cryptographic signature or real-model quality claim.

Failures corrected: first real process attempt exposed a PostgreSQL PL/pgSQL local-record/table-alias ambiguity in a job guard, fixed by distinct table alias. Later added negative tests initially lacked select/LostLease/text imports after automatic unused-import cleanup; corrected, then reran. An intermediate focused run56passed/17skipped preceded the final authority/transition additions. Latest focused run23passed/16skipped,29.26s including runtime-role migration test. All lint/format/compile and Node3 tests pass; full final suite is running and will be recorded below. No separate mypy/pyright or remote CI run is claimed.

Exact commands used (PowerShell):
```powershell
docker run -d --rm --name caliburn-checks-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest tests/test_factory_checks.py -q -x
.venv/Scripts/python.exe -m pytest tests/test_factory_checks.py tests/test_factory.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x --junitxml=docs/evidence/m3-static-focused.xml
.venv/Scripts/python.exe -m pytest tests/test_factory_checks.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x --junitxml=docs/evidence/m3-static-focused.xml
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m3-static-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
node --test tests/timeline_stream.test.mjs
```

Migration/rollback: additive0006 after0005. Only disposable test schemas were upgraded/downgraded by tests; no deployed DB changed. Disabling flag affects new tasks, not already pinned policies; stop/drain granted tasks during rollout/rollback. Preserve evidence when rolling back code. Explicit backup/operator approval is required to downgrade to0005, which deletes static check requests/reports/mappings, not source bundles. Operator-provisioned roles need separate offboarding. New code invalidates old factory task digests rather than silently changing verifier implementation.

Changed files: tool_factory contracts/schema/service/API plus new checks/static_check/verifier modules, runtime store/worker/API/chat/config, Compose/example, migration0006, tests/conftest/factory_checks and existing runtime-role test; ADR0011/runbook/architecture/security/contracts/acceptance/plan/README/progress and JUnit evidence. Overall goal stays active: remaining M3 includes independent source execution approval, isolated behavior/property/replay/resource tests, complete security/dependency/license qualification, signing, production registry and measured invocation reuse; M4 identity/broker and M5 memory/routing/customer release remain incomplete. Next priority is the separate executable-qualification approval/admission boundary, preserving no-self-approval and no authority inheritance from static reports.


Full regression before final startup-diagnostic hardening: **237 passed / 45 skipped / 0 failures**,306.54s;1 existing upstream TestClient deprecation warning. JUnit docs/evidence/m3-static-pytest.xml. Four skips are the still-unapproved Git-image qualification;41 are DB-specific applicability cases. PostgreSQL and previously admitted data/reviewed-test Docker cases actually ran; no Factory code execution or new Git image occurred.

Additional concrete boundary finding: an invalid synthetic DB port value was echoed by SQLAlchemy startup parsing before the verifier CLI try/except. The reproduction printed only exit/marker-presence booleans, not a raw DSN/trace. Moved settings/engine creation inside the sanitized exception boundary and guarded disposal; new subprocess regression requires exit2/generic diagnostic and excludes the synthetic config marker. Final focused Factory/proposal/runtime-role regression was rerun after this last fix; result recorded below. Full M1/M2 regression above precedes this CLI-only fix, not falsely claimed to include the new case. Static checks/compile were rerun on the final source; no mypy/remote CI claim.

Final packaging command `uv build --wheel --offline --out-dir .caliburn/package-check` succeeded (build log .caliburn/package-check/static-wheel.log). ZIP inspection proves all8 Factory module bytes match final source, including startup hardening. `docker compose config --quiet` passed with synthetic compose-fixture variables and default-off flags; no service was installed or started. Code/schema migrations were exercised only in disposable fixtures, not deployed data.


Final focused validation after startup fix: **58 passed / 18 skipped / 0 failures**,53.57s,1 existing upstream TestClient warning. m3-static-focused.xml covers final Factory queue/verifier/CLI/proposal and runtime-role migration paths, including the new malformed-startup diagnostic case. Full regression result remains237passed/45skipped as separately scoped above. Ruff/format120 files, compile, Node3, Compose config and final byte-matched wheel checks PASS.

Cleanup commands: `docker ps -a --filter label=caliburn.sandbox=managed-v2 --format '{{.Names}} {{.Status}}'` returned no managed containers; PostgreSQL reviewer/verifier temporary-role count0. `docker stop caliburn-checks-postgres` stopped/removed only this disposable --rm database. Prior images, deployment volumes, operator package and unrelated services were preserved. No persistent verifier role/daemon, source execution grant, Git image or customer deployment was created. M3.2a is done; full goal remains active and incomplete.


## M3.2b.1 — separately reviewed Factory sandbox tests (2026-11-08)

Previous goal turn classification: progress, actual separate-role/process static triage plus237passed/45skipped full regression and final58passed/18skipped Factory hardening checks. Current source/runbooks/approval/driver/schema were inspected. The prior Git-image build/license approval remains unanswered and was not inferred from automatic continuation. No Git image/package, persistent role/grant/customer deployment or commercial call was enabled.

Plan/impact: concrete default-off Factory request/wait/independent decision/runtime wake/isolated test/result consumer, not a source-executable interface stub. Add execution contracts, Qualification, ExecutionQueue and separate trusted-host control CLI under tool_factory; migration0007 with6 tables, runtime/API/chat/config/Compose integration, role/process/Docker tests, ADR0012/runbook and evidence. Reuse the existing immutable approved reviewed-test image and driver; no new dependency/image build or license/branding assumption. Source stays QUARANTINED; production registration and signing remain separate/unbuilt.

Implemented: operator-owned immutable plan binds exact candidate/static report/generated+fixed+independent tests/image/TTL. Only tool-kind stdlib candidates with no permission/dependency requests and current independent REVIEW_REQUIRED static report are admitted; BLOCKED/MCP/Skill/dependency/permission cases fail closed. Independent REVIEWER/EXECUTOR mappings are separate from static and repository review roles and have no Task mutation rights. Reviewer cannot equal source/request/plan/static author or Task actor and appends only expiring hash-bound decisions/revocations. Runtime alone wakes actionable/latest reviewed waits, with no starvation from21 unrelated waits. Client flag/identity/authority fields cannot enable execution; CALIBURN_ALLOW_FACTORY_EXECUTION=false by default, with pinned execution/factory digests for new admitted tasks.

Execution consumer: a separate host supervisor uses an EXECUTOR connection and fixed Docker driver, while API/runtime have no Docker/host-shell route. Exact request/scope/current role/hash/image/expiry/lease/task state is checked at enqueue/claim, after actual container inspection before source delivery, during execution and before result publication. Wrong-image consumers do not claim/deny another image's queue. Actual generated tests, strict recursive type/value fixture probes and owner-provided independent tests run in nonroot/network-none/read-only-root/cap-drop/seccomp/resource-bounded fresh containers with no socket/host bind/credentials. Typed bounded TestRun status/exit/output/source/plan hashes are wrapped with actual executor identity/request/binding/image and committed atomically to an immutable terminal job. Passing transport can contain FAILED/TIMEOUT/OUTPUT_LIMIT; production_approved=false/security INCOMPLETE/license UNREVIEWED always. Transport failure may have unknown source execution, not proof of no execution.

Real evidence with fixture model/identity: two candidates execute through an independent reviewer and separate actual executor OS process. Correct double function PASSED3 tests; incorrect x3 function's tautological generated test passed, while fixed declared fixture and operator independent extra case both failed (6!=4,15!=10), producing actual FAILED/exit1. This demonstrates why merely storing/passing generated tests is insufficient. An actual worker child exits73 after receiving already persisted evidence but before tool checkpoint; natural1-second lease expiry and a replacement worker reuse1 job/1 dispatch/1 queued event, with3 charged tool calls (review+execution+replay). No extra container is dispatched. Actual infinite-loop TIMEOUT, output overflow OUTPUT_LIMIT, running-container revoke/cancel/pause cleanup, predispatch reject/revoke/offboarding/deadline/cancel, cross-actor/tenant/image/plan/receipt denial and server-only API flag were exercised. Synthetic NOLOGIN role fixtures use actual PostgreSQL ACL/current_user boundaries but are not customer human/OIDC credentials. Passing child status is not malicious-subject/test anti-tamper certification.

Security correction: a new red SQL test reproduced a disabled execution reviewer restored by its own TEMP factory_exec_roles shadow table. Migration0007 pins13 Runtime/Policy/Factory trigger lookup paths to the trusted application schema with explicit pg_temp last, leaving pg_catalog implicitly first and invoker current_user intact; no SECURITY DEFINER or expanded privilege. Regression temp-map attacks against Factory execution/static and existing repository review all now fail (3passed/3SQLite applicability skips in m3-trigger-path-negative.xml). Shared hardening deliberately remains when only0007 execution tables are downgraded. Direct DB services/owners remain trusted; no RLS/compromised-host isolation claim.

Implementation failures corrected: first strict Factory result validation rejected generic sandbox transport's unrelated candidate_ref/default empty-data fields; an explicit typed projection now handles positive/negative results without changing the shared runner contract. Plan receipt replay now validates exact requested plan/body/hash rather than merely finding an old call key. Initial intermediate tests11passed/11skipped, then17passed/17skipped with real crash/resource cases, then19passed/19skipped including scope/image guards and runtime-role migration check. First expanded full regression258passed/65skipped/0failed,414.05s before final temp-lookup security hardening. Final full regression including those three negative cases is running; result is recorded below. One documentation update hit Windows cp949 decoding on Korean README text; it wrote nothing, then explicit UTF-8 reads/writes completed.

Exact observed commands (PowerShell):
```powershell
docker run -d --rm --name caliburn-exec-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
$env:CALIBURN_RECORD_FACTORY_EVIDENCE='true'
.venv/Scripts/python.exe -m pytest tests/test_factory_execution.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x --junitxml=docs/evidence/m3-execution-focused.xml
.venv/Scripts/python.exe -m pytest tests/test_factory_execution.py::test_temporary_table_cannot_restore_disabled_review_authority tests/test_factory_checks.py::test_temp_mapping_cannot_restore_static_verifier tests/test_review.py::test_temp_mapping_cannot_restore_repository_reviewer -q -x --junitxml=docs/evidence/m3-trigger-path-negative.xml
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m3-execution-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
node --test tests/timeline_stream.test.mjs
uv build --wheel --offline --out-dir .caliburn/package-check
# Final build log: .caliburn/package-check/execution-wheel.log; ZIP byte inspection verifies12 modules.
$env:CALIBURN_DB_ADMIN_PASSWORD='compose-fixture-admin'
$env:CALIBURN_DB_PASSWORD='compose-fixture-runtime'
$env:CALIBURN_API_TOKEN='compose-fixture-service'
docker compose config --quiet
```

Ruff/format129 files, compile, Node3 tests, offline wheel and Compose config PASS. Final wheel12 Factory modules byte-match source. Existing TestClient upstream deprecation warning remains; no separate mypy/remote CI/push/commit claim (workspace still has no Git repository). Structured actual fixture results: docs/evidence/m3-execution-passed.json and m3-execution-failed.json; optional recording flag writes only these fixed local files, not credentials/DSNs/leases. Final full suite refreshes these records; JUnit links scopes/counts above/below.

Migration/rollback:0007 adds6 execution tables and fixes shared trigger paths; only disposable fixture schemas migrated, not an existing deployed DB. Drain/cancel incompatible digest-pinned work before code/schema rollout. Disable new grants via server flag; disable/revoke mapped authority for active admission. Mapping disablement does not revoke DB SELECT/LOGIN credentials; operator offboarding/rotation is separate. Prefer code rollback retaining evidence. An explicit backed-up downgrade to0006 deletes execution plans/requests/decisions/revocations/jobs/mappings and needs operator approval, retaining candidates/static reports/runtime history and shared lookup hardening. Preprovisioned DB roles require separate offboarding.

Remaining: broad property/negative/replay/poison/SAST/dependency/license/anti-tamper qualification; MCP/Skill/nonstdlib execution adapters; independent signing/production activation/qualified invocation reuse/drift regression; live-model/real-repository performance and enterprise identity/broker/memory/routing/customer operations/legal clearance. Source-test subset is real, not full M3 or Codex-level autonomy. Next priority is qualified-artifact governance/signing/activation with explicit evidence requirements, without turning incomplete sandbox observations into production authority. Goal remains active.


Final expanded verification including trigger-lookup hardening: **261 passed / 68 skipped / 0 failures**,413.23s;1 existing upstream TestClient deprecation warning. m3-execution-pytest.xml has329 cases. Four skips remain unapproved Git-image qualification;64 are DB-specific applicability cases. Actual PostgreSQL/independent OS processes/existing data+reviewed-test+Factory Docker cases ran. No Git image was built. Ruff/format129 files, compile, Node3, final wheel12 byte-matched modules and Compose config PASS. No persistent application deployment/database migration/credential mapping was enabled.

Final structured fixture evidence:

- m3-execution-passed.json: Task 50ac21a9-ecb1-47f8-b300-3f72be6052d5, request 4133e711-8523-403f-b3ae-55e61a71e6bb, PASSED, exit0, source SHA 86007fae27119248f3cf0c7d3f49c6e6048adc026ac549ef402481cd96afc494
- m3-execution-failed.json: Task f23aa530-4af8-42da-8360-109535b8b67a, request cd7bb320-404d-4bc2-a6b2-cf7fd7960316, FAILED, exit1, source SHA 4a65f46d542cf74b3abc7fcc2139a321450b3f8bac6362920900881e7f910ec0

Cleanup verified: no managed-v2 containers,0 temporary reviewer/verifier/Factory reviewer/executor roles. `docker stop caliburn-exec-postgres` stopped/removed only this disposable --rm test DB. Prior images, deployment volumes, operator package and unrelated services were preserved. All child test/worker/executor processes ended through fixture wait/cleanup paths. M3.2b.1 is implemented, full M3/enterprise goal remains active and incomplete.


## M3.3a — independent evidence integrity; approved Git qualification and live LLM (2026-11-08)

Previous goal turn classification: progress, completed separately reviewed Factory sandbox execution subset with261passed/68skipped. Overall enterprise goal remains active/incomplete. This turn the user explicitly approved the previously reviewable Git development image build/local fixture tests, supplied an ignored API credential file, selected https://github.com/leemg1476/CALIBURN and authorized paid LLM calls with a50,000 input+output token/100-call cumulative ceiling. This authorizes the exact development build/test and paid synthetic smoke; it is not source production activation or customer redistribution approval.

Plan/impact: actual independent signer/public verifier/API and cross-task evidence consumer, not interface-only registry; additive migration0008 and backend cryptography dependency. Preserve EVIDENCE_ONLY/noninvokable/no-self-approval; no keys in runtime/model/sandbox. Expected files: artifact_integrity/registry/signing_control, Factory schema/contracts/service/API, migration0008, signed-evidence tests/fixtures, dependency metadata, ADR0013/runbook and plan/progress. Also qualify the approved Git image and verify the supplied real model with bounded durable tool calls. No deployed schema or existing customer data is changed.

Implemented: owner-only immutable public key/role trust and irreversible revocation; independently signed full source/test/manifest/dependency declarations plus exact static/approval/execution/plan/checkpoint evidence, domain-separated actual Ed25519 signatures, scoped bounded strict envelopes, duplicate/nonfinite/algorithm/time/hash/scope denials, separate signer process encrypted-private-key loading, verified idempotent import/export, offline public-key verification without DB/private material, live key/mapping/review/source checks and immutable receipts. Authenticated no-store artifact API and existing cross-task capability lookup actually consume verification. Every admission remains can_invoke=false/activation_eligible=false/production_approved=false. No active registry, production release approval or production signer custody is implied. Synthetic crypto unit fixtures are labeled; actual PG/Docker/signer process cases use real generated test execution and ephemeral encrypted keys, not fabricated signed platform evidence.

Security/implementation corrections: first PG migration test exposed a JSONB regex operator mismatch; use ->> text extraction and explicit missing-signature denial. Added runtime-role write-deny checks for all3 new tables and a real temporary mapping shadow attack against disabled signer authority, protected by trusted-schema/pg_temp-last trigger paths. Key revocation is idempotent; whole-second issuance/key not-before values avoid fractional-time false rejection. Online verification checks current public trust/source graph, while offline verification cannot claim live revocation. No SECURITY DEFINER/RLS/compromised-owner claim. Signing CLI sanitizes startup/key/DSN exceptions. Earlier missing select/update/LostLease test imports were corrected before focused green runs.

Approved Git image: exact Dockerfile.git build succeeded with pinned Git1:2.47.3-0+deb13u1/base unchanged. Image sha256:304e6307141490b6f48d0bb0763411b19464873e422530e7a02b1e37318f572a, actual git version2.47.3. An additional no-network/read-only/no-mount inventory container retained118 installed package versions and Git copyright in docs/evidence/git-dev-image-inventory.json. Previously pending actual Git Docker isolation/worker/timeout/cancel cases now run. No live repository grants, upstream-history clone, remote write or customer package release was created. Prior skipped evidence remains historical.

LLM: actual filename is .env.apikey; only explicit CALIBURN_API_ENV_FILE loads bounded nonexecuting aliases, and pytest clears that variable. Values never printed/committed/included in model messages, traces or evidence. Environment overrides file; reading does not enable network/Factory permissions. Settings repr excludes secret/key/DSN; upstream URL credentials/query/fragment rejected. Official OpenAI Chat profile uses max_completion_tokens/store=false/default service tier and gpt-6-luna reasoning_effort=none per official docs; local-compatible max_tokens stays supported. No automatic redirect/fallback. Real opt-in script with persistent ignored reserve-before-call ledger completed PostgreSQL task4b85498e-7170-427b-8c31-a1af16912e34:19+23=42 then42+5=47 using actual add_numbers twice and final47.3 model requests,745 reported tokens (699input/46output), leaving97calls/49,255tokens. No further paid call was needed for this smoke. Evidence docs/evidence/live-llm-smoke.json; this is not a repository coding-quality benchmark. The ledger is single-process development accounting, not an enterprise account-wide quota;0.01 cost reservation is not vendor billing. Commercial fallback remained false.

Dependencies: cryptography50.0.2 Apache-2.0 OR BSD-3-Clause installed with binary-only wheels, observed cffi2.1.1 MIT-0 / pycparser3.12 BSD-3-Clause. License file hashes in signing-dependency-inventory.json; binary OpenSSL notices/transitive complete SBOM/security/customer legal clearance remain open. No Open WebUI source/branding/license assumptions changed. Git development approval is distinct from redistribution clearance.

Git: initialized local main with origin matching the user's empty PUBLIC GitHub repository. No preexisting remote refs were found; no initial commit/push/public publication is yet claimed. Ignored env/cache/venv/build/runtime files are excluded. Public publication must respect the original explicit external-change approval gate and proprietary ownership notice; finish local reviewable evidence and preflight first.

Exact commands used (PowerShell; synthetic fixture credentials only):
```powershell
docker run -d --rm --name caliburn-signing-postgres -e POSTGRES_HOST_AUTH_METHOD=trust -e POSTGRES_DB=caliburn_test -p 127.0.0.1:55432:5432 postgres:17-alpine
uv pip install --python .venv/Scripts/python.exe --only-binary=:all: cryptography==50.0.2
docker build -f deploy/sandbox/Dockerfile.git --build-arg CALIBURN_ALLOW_GIT_DEV_IMAGE=true -t caliburn-sandbox:git-dev .
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_SANDBOX_TEST_IMAGE=(docker image inspect caliburn-sandbox:m2 --format '{{.Id}}')
$env:CALIBURN_GIT_TEST_IMAGE=(docker image inspect caliburn-sandbox:git-dev --format '{{.Id}}')
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest tests/test_git_boundary.py tests/test_signed_evidence.py tests/test_sandbox.py::test_migration_blocks_runtime_self_grant_in_postgres -q -x --junitxml=docs/evidence/m3-signing-git-focused.xml
.venv/Scripts/python.exe -m pytest tests/test_llm.py -q
# Owned disposable caliburn_live_20261108 schema created; no other queue in this schema.
$env:CALIBURN_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test?options=-csearch_path%3Dcaliburn_live_20261108'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/live_llm_smoke.py --allow-paid --api-env-file .env.apikey
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m3-signing-pytest.xml
.venv/Scripts/python.exe -m ruff check .
.venv/Scripts/python.exe -m ruff format --check .
.venv/Scripts/python.exe -m compileall -q src migrations scripts
node --test tests/timeline_stream.test.mjs
uv build --wheel --offline --out-dir .caliburn/package-check
# Log signing-wheel.log; ZIP checks15 Factory modules + config/llm bytes against source.
$env:CALIBURN_DB_ADMIN_PASSWORD='compose-fixture-admin'
$env:CALIBURN_DB_PASSWORD='compose-fixture-runtime'
$env:CALIBURN_API_TOKEN='compose-fixture-service'
docker compose config --quiet
git init -b main
git remote add origin https://github.com/leemg1476/CALIBURN.git
git ls-remote origin
```

Focused result34passed/10skipped/0failures,80.13s; no Git-image cases skipped. LLM adapter unit result6passed/0failed; HTTP transport mocked there. Ruff/format138files, compile, Node3, Compose config and final offline wheel byte-check PASS. Full PG/all3Docker-image regression is running; final result/skip reasons/cleanup follow below. No separate mypy/pyright, hosted GitHub CI or public push is claimed.

Migration/rollback:0008 adds only registry_roles/signing_keys/signed_artifacts and2 trigger functions. New functions use trusted-schema search paths; existing0007 hardening remains. Only disposable schemas migrated, no deployed DB. Drain/reconcile pinned Factory tasks before rollout; stop signers/new requests before rollback. Prefer compatible code rollback retaining immutable evidence. Explicit backed-up downgrade to0007 deletes the3 new trust/evidence tables and2 functions, retaining older source/test evidence and trigger hardening. Test roles/keys/containers are ephemeral; no production signer/reviewer daemon installed. Detailed boundaries: SIGNED_EVIDENCE.md/ADR0013/LIVE_MODEL_VALIDATION.md.

Remaining: full malicious-subject/test anti-tamper and property/poison/replay/SAST/dependency/license qualification (M3.2b.2); release approval and active version-pinned registry/invocation/rollback/reuse (M3.3b/M3.4); real-repository live-model coding benchmark (M2.4b); M4 OIDC/broker/revocation and M5 validated memory/routing/customer-release operations. Next development priority is qualification integrity before active generated-code reuse; do not treat evidence signing or arithmetic smoke as clearance.


Final regression: **285 passed /73 skipped /0 failures**,519.28s,1 existing upstream Starlette/HTTPX TestClient deprecation warning. JUnit docs/evidence/m3-signing-pytest.xml. All73 skips are DB-specific applicability (PostgreSQL-only authority/concurrency/trigger cases on SQLite, plus SQLite-only denial cases on PostgreSQL), not missing Git/Docker/PG configuration. Approved actual Git container cases and separate signer PG/Docker cases ran. Fixture inference is still used by ordinary regression; the independently recorded real API smoke is3calls/745tokens. Static/format/compile/Node/Compose/offline package checks above passed on final source; later edits only documentation/example comments. No extra paid calls were made.

Cleanup verified0 remaining temporary authority roles and0 managed-v2 containers. Stopped/removed only the owned --rm caliburn-signing-postgres container; its disposable live-smoke schema and synthetic fixture DB vanished with it. Sanitized JSON/JUnit evidence and ignored cumulative paid-usage ledger are retained. Approved development images, unrelated services/volumes and existing source are preserved. No durable production signer key/role/grant/daemon was created.

Publication preflight examined prospective nonignored initial source/evidence (~2MB):0 matches for the supplied actual API key and0 token/private-key marker matches; env/API files, budget ledger, virtualenv, caches and build/runtime directories ignored. This is bounded preflight, not complete secret certification. Final staged bytes will be rechecked before the local commit; the selected GitHub origin is PUBLIC, so no public push occurs without the original requested external-change approval.


### Approved GitHub publication and Linux CI correction

The user explicitly approved public initial publication of320a053 (196files); `git push --set-upstream origin main` succeeded and remote refs/heads/main exactly matched320a053a27cecdfac3e8a50d94285a991ebb43da. Working tree was clean. GitHub CI installed dependencies and passed Ruff/format/Node plus both existing Python sandbox image builds, then exposed14 fixture failures:267passed/77skipped/14failed on unprivileged Ubuntu26.04/Python3.12.16 (run42478707833). All failures were direct inert-data-runner fixtures trying to create host /work; Windows local tests had not exposed this host-root assumption. This is not a green hosted result; concise evidence github-ci-initial.json retains the exact failures. Four approved local Git-image cases are intentionally not configured in the current hosted workflow, hence77skips rather than local73.

Correction: the autouse pytest fixture maps only the imported fixed-data-runner Path('/work') to each test's tmp_path/data-runner. It never creates/chmods the host root, never changes production runner code/paths, never imports generated candidate code, and never changes actual Docker tests (the container loads the original runner independently). Existing host fixtures continue to use real fixed inert patch logic, not a fabricated result; container isolation claims rely on actual separate Docker tests. No new dependencies/images/privileges or migration/ADR decision is introduced.

Command: with the separate disposable caliburn-ci-fix-postgres and the existing data/reviewed-test image environment, `.venv/Scripts/python.exe -m pytest tests/test_candidate_ancestry.py tests/test_review.py tests/test_task_checkout.py tests/test_reviewed_execution.py::test_readonly_or_review_only_is_not_execution_authority -q --junitxml=docs/evidence/ci-host-path-focused.xml` →37passed/10DB-applicability skips/0failed,79.42s. Ruff and format on all138files and Git whitespace checks (cr-at-eol on Windows) PASS. The initial Git whitespace command treated CRLF bytes as trailing whitespace; rerunning with cr-at-eol correctly passed without rewriting source/implementation digests. No extra paid API calls. This test-only correction is the follow-up to the approved initial GitHub publication; hosted full regression must be rechecked after its push.
