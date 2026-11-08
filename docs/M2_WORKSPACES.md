# M2 workspace data operations — development runbook

This running slice adds isolated source list/read/literal-search and inert patch proposals to M1. It does **not** run repository tests or generated code, approve a candidate, modify a host repository, publish a tool or write to an external service. The full secure coding agent remains in progress. A separate opt-in reviewed stdlib test consumer is now available; see REVIEWED_TESTS.md. This data runner remains non-executable.

## Components and privileges

- API: accepts a workspace reference already registered for the server-owned actor/tenant.
- Runtime worker: records a typed sandbox job and waits for its durable result; no Docker/subprocess import or host shell.
- Operator importer: explicitly grants a bounded reviewed snapshot using an operator-owned DB connection. Not an HTTP route or model tool.
- Trusted supervisor: a separate host control-plane process with existing operator Docker access and a non-admin DB connection. It only creates the fixed sandbox configuration. Do not place its Docker access in an agent container or expose it through a socket proxy/public API.
- Task container: fresh non-root, network-none, read-only-root instance of a reviewed immutable local image; no host mounts, vault/platform tokens, Docker socket or model.

The default Compose services do not install/start the supervisor or acquire Docker privileges. Development uses a single fixed service actor/tenant; OIDC/service identity and production authorization remain M4. M1 runtime DB role `caliburn` is denied workspace-grant INSERT/UPDATE/DELETE by migration 0002. Import/revoke require an operator connection. Run read/patch jobs with a runtime connection, never a database administrator credential in an agent/container.

Current application schema head is 0004. The following 0002 notes describe the original data-only slice; later review/ancestry evidence must also be preserved. Use current-head upgrade and conservative rollback in ADR 0006/REPAIR_LOOP.md, not a blanket legacy downgrade.

## Schema rollout and rollback

`0002_workspace` adds nullable `runtime_tasks.workspace_ref`, `sandbox_workspaces` and `sandbox_jobs`. Workspaces hold immutable text bundle/hash, actor/tenant, permissions, provenance, status and expiry. Jobs hold task/step ownership, input, attempts, controller lease, immutable image and bounded result. M1 rows remain valid; omitted/None workspace references keep the old normalized idempotency hash. No M0 SQLite import or host source modification occurs.

Before upgrade: stop dispatch, back up the private DB and verify restore. Use an owner connection for `alembic upgrade head`; switch API/worker/controller back to runtime credentials afterwards. Do not give the runtime role DDL or workspace-grant write privileges.

Rollback requires stopping all processes, preserving snapshot/job evidence and a DB backup, then an explicitly approved `alembic downgrade 0001_runtime` and deployment of the preceding application version. This removes only M2 tables/reference column; it is destructive to M2 records. Automated downgrade/reapply is tested only in disposable schemas. No customer database was downgraded.

## Build a reviewed fixed runner

```powershell
docker build --file deploy/sandbox/Dockerfile --tag caliburn-sandbox:m2 .
$image = docker image inspect caliburn-sandbox:m2 --format '{{.Id}}'
# Review/pin this immutable sha256 image ID before operator activation.
```

The runner adds no third-party Python dependencies and receives only a JSON bundle on stdin. It never imports repository modules, evaluates source, accepts a shell command or installs a package. It supports 128 UTF-8 files, 64 KiB/file, 1 MiB total, bounded wire/output sizes and validated relative paths. Traversal, SCM-private/credential paths, links, binary input, collisions and oversized requests are denied. Explicit `.github`/`.gitignore` project files are allowed; their text cannot authorize operations.

Each job uses memory/swap=128 MiB, CPU=0.5, PID=32, nofile/nproc limits, user=10001:10001, cap-drop ALL, no-new-privileges, seccomp, network none and a 16 MiB noexec/nosuid/nodev `/work` tmpfs. There is no host mount. The supervisor inspects actual container configuration before delivering input, validates source revision/output contracts, and removes only its generated container name. The runner has an independent 25-second lifetime. This is local development isolation evidence, not proof against hostile native-code/container escapes or rootless/microVM qualification.

## Operator workspace registration

In an operator shell with a private **operator DB connection** configured:

```powershell
# Explicit files from an operator-controlled quiescent directory:
$workspace = .venv/Scripts/python.exe -m caliburn.sandbox.importer --root C:/path/to/repo --file calc.py --file README.md --propose-patch
# Alternatively add --git-commit <full immutable 40/64 hex commit> to read committed blobs.
```

Without `--propose-patch`, only read operations are granted. The CLI rejects known configured platform credential values. General user-secret DLP is not built; review the selected bundle. Directory mode is not designed for an adversarial concurrently mutated filesystem. Git mode reads exact local commit/blob objects, never the uncommitted working tree; records commit/blob hashes; disables hooks, fsmonitor, credential helpers, replacement refs, glob pathspecs and lazy fetch. It rejects partial clones, included configuration, alternate object stores, linked metadata, symlinks and submodules. No clone/fetch or network checkout exists. Git is an existing operator-host dependency, not bundled in the sandbox. Guard flag semantics were checked against [official Git documentation](https://git-scm.com/docs/git); the target host's existing Git 2.31 was exercised with additional partial-clone/alternate rejection.

Grants expire after one hour by default (programmatic TTL bounded to one day). A trusted operator can revoke a grant with `WorkspaceQueue(operator_store).revoke(workspace_id)`; there is no model or HTTP grant-minting/revoke tool. Expiry/revoke or changed content/hash prevents submission/new dispatch/result delivery; it cannot erase already authorized historical reads.

## Runtime and trusted supervisor

In separate shells with a **non-admin runtime DB connection**, start the existing API/worker and:

```powershell
.venv/Scripts/python.exe -m caliburn.sandbox.control --image $image
```

The supervisor host must reach the approved private PostgreSQL endpoint; the offline Compose profile does not publish its DB to the host. Do not attach a Docker socket to a worker to bypass this separation. The control-plane program remains operator-started; this change does not install a persistent service or alter host permission groups.

Submit a task through `POST /api/v1/tasks` with `prompt`, `workspace_ref` and limits. The server resolves the granted bundle and tool permissions and pins both hashes. A missing/wrong-scope/expired reference is 404. The runtime exposes repo_list/read/search and repo_patch only when allowed by the grant. Model input cannot set actor, tenant, Docker flags, host path, grant scopes or approval status.

repo_patch requires an exact base SHA and unique old text; returns candidate content/hash/diff with approved=false and executable=false. It changes neither the registered base nor the repository. A stale base or ambiguous replacement yields a typed error. Candidate source remains inert pending an independent approval/execution contract in a later unit.

Each request binds to the task/step/lease and has one durable result. Completed sandbox results survive worker restart without repeating the operation; pending read/patch operations can retry. Stale task/controller leases cannot commit. Controller retries are bounded by min(3, task max_retries+1). Pause/cancel/deadline/expiry/revoke stops dispatch/result publication and cancels local work. There is no exactly-once external side-effect claim; no such operation is enabled.

## Validation and actual process demo

```powershell
# Against a disposable loopback PostgreSQL test DB as described in M1_RUNTIME.md:
$env:CALIBURN_TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_SANDBOX_TEST_IMAGE = $image
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests migrations scripts
.venv/Scripts/python.exe -m ruff format --check src tests migrations scripts
.venv/Scripts/python.exe -m compileall -q src migrations scripts
# Owner connection only to the disposable test database for fixture setup:
$env:CALIBURN_DATABASE_URL = $env:CALIBURN_TEST_DATABASE_URL
$env:CALIBURN_API_TOKEN = [guid]::NewGuid().ToString('N')
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/demo_workspace.py --image $image
```

Tests use real PostgreSQL and real Docker when both variables are supplied; unset variables produce explicit skips, not integration evidence. CI builds a runner image and enables real-container tests. Docker tests check actual cgroup/kernel state, absence of Docker socket/network interfaces, stale-base refusal, timeout and pause/cancel/revoke cleanup. The role-denial test creates a no-login role inside a rolled-back isolated PostgreSQL transaction, verifies SQLSTATE 42501 on runtime grant writes, and leaves no role/grant behind.

The demo starts separate API, scripted fixture worker and trusted supervisor processes; submits over real HTTP; performs list/search/read/patch; verifies four SSE sandbox completion events; stores `docs/evidence/m2-workspace-demo.json`; then stops its processes. All inference is mocked. PostgreSQL, queue, source operations, diff, containers, isolation and transport are real. No actual repo tests or external writes occur.

## Next required units

Real task-local Git checkout; independent approval bound to exact candidate/runner/tool digests; approved test execution in a stronger qualified sandbox; bounded repair using actual independent test evidence; fixed-repository benchmark and failure taxonomy; approved scoped external writes. Factory signing/registry, tenant OIDC/Vault, evaluated memory/skills and customer license/SBOM clearance are still required. The current read/patch slice does not satisfy or replace those deliverables.
