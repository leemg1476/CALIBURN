# M1 durable runtime — runbook and boundaries

This is a running backend slice. Inference in the recorded demo is a deterministic fixture, not a real LLM. PostgreSQL, API, separate worker, queue, checkpoints and SSE transport are real.

## Local PowerShell run

Use Python 3.12+; the machine default Python 3.10 is insufficient.

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv/Scripts/python.exe -e '.[dev]'
# Supply a private PostgreSQL DSN through the environment; never paste it into prompts/logs.
$env:CALIBURN_DATABASE_URL = <your-private-PostgreSQL-DSN>
$env:CALIBURN_API_TOKEN = [guid]::NewGuid().ToString('N')
$env:CALIBURN_PROVIDER = 'fixture'
.venv/Scripts/python.exe -m alembic upgrade head
# Separate terminals with the same environment:
.venv/Scripts/python.exe -m uvicorn caliburn.app:app --host 127.0.0.1 --port 8000
.venv/Scripts/python.exe -m caliburn.runtime.worker
```

The DSN above is a placeholder, not an executable PowerShell expression. Use your deployment's private secret provisioning. API/worker DB credentials must be non-superuser, have no schema CREATE/TRUNCATE, and have only runtime table access. Migrations require a separate database owner. Compose implements this separation for a new volume.

## Compose offline fixture deployment

```powershell
$env:CALIBURN_DB_ADMIN_PASSWORD = [guid]::NewGuid().ToString('N')
$env:CALIBURN_DB_PASSWORD = [guid]::NewGuid().ToString('N')
$env:CALIBURN_API_TOKEN = [guid]::NewGuid().ToString('N')
docker compose up --build --detach
```

Use URL-safe passwords or percent-encode them in DSNs. Retain credentials in your approved secret manager; recreating random passwords against an existing volume does not rotate its role passwords. The bootstrap role script only runs for a new PostgreSQL volume. No existing database is imported or overwritten.

API binds loopback port 8000. API and worker are non-root, read-only, drop all capabilities and have no host filesystem or Docker socket. The internal network denies external egress. The only mount of repository content is a reviewed bootstrap script into the database initialization directory, not an agent mount. Real upstream model access needs a future explicit approved egress route; the offline Compose profile does not open it.

No Open WebUI image is bundled, rebranded or licensed by this change. Connect a separately authorized Open WebUI instance to `/v1`, choose `caliburn-agent-durable`, and use normal streaming or nonstreaming completion (completion-level compatibility, not live provider tokens). The durable adapter submits a real task, awaits up to 90 seconds, and returns `caliburn.task_id`/`events_url`. After HTTP timeout the task continues and can be queried. Context is flattened into bounded user content; this adapter is not a lossless multi-turn message/attachment bridge. Actual pinned/unmodified WebUI browser smoke is now verified with fixture inference; the product task timeline remains pending. See OPEN_WEBUI_SMOKE.md and ADR 0003.

## Task API

All routes except `/healthz` require the development service bearer. Actor and tenant are fixed server-side; request `user`, role or tenant fields cannot authenticate a caller. This is not OIDC or production tenant isolation.

```powershell
$headers = @{ Authorization = "Bearer $env:CALIBURN_API_TOKEN"; 'Idempotency-Key' = [guid]::NewGuid().ToString('N') }
$body = @{ prompt = 'sum 2 3'; limits = @{ max_steps=6; max_tool_calls=16; max_tokens=64000; max_cost=0; timeout_seconds=300 } } | ConvertTo-Json -Depth 5
$task = Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/api/v1/tasks -Headers $headers -ContentType application/json -Body $body
Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/tasks/$($task.id)" -Headers $headers
# POST /api/v1/tasks/{id}/pause, /resume, /cancel
# GET /api/v1/tasks/{id}/events with Last-Event-ID: <last integer sequence>
# Add ?follow=false to read available events and close.
```

Matching idempotency key + normalized body returns the same task; changed body returns 409. Pause preserves checkpoint; resume queues a new run. Cancel is terminal and idempotent. Terminal tasks cannot resume. WAITING_APPROVAL is reserved and fail-closed: there is no independent approval service or self-approval API in M1.

## Recovery and budgets

PostgreSQL queue rows use SKIP LOCKED. Default lease is 15 seconds; heartbeat is at most 250 ms. After process death another worker claims the expired lease and continues from the committed conversation. Old lease tokens cannot heartbeat or commit. State, step result, conversation checkpoint and event commit atomically. PostgreSQL rejects UPDATE/DELETE on events; a database administrator can bypass database-level controls, so this is not immutable external audit retention.

A crash after execution but before commit causes an at-least-once retry. M1 admits only reviewed read-only arithmetic/clock tools, with typed contracts and a pinned source digest. Completed tools are not repeated. Mutable/generated/side-effect tools cannot run. Retry attempts consume budgets, including calls and conservative model token/cost reservations. A code revision change rejects old task tool policy rather than silently changing behavior.

Limits cover model calls, tool calls, retries, total token reservations, total cost reservations, wall time and per-call time. Wall time starts on first claim and continues during pause. Token reservation uses serialized context/schema byte length + framing allowance + maximum output tokens; the configured upstream output ceiling is sent as `max_tokens`. Cost uses a configured conservative per-call reservation, not a verified invoice. Upstream provider configuration must set positive `CALIBURN_MODEL_CALL_COST`; each task must supply sufficient `max_cost`. The durable chat adapter uses `CALIBURN_TASK_MAX_COST` (default 0) and `CALIBURN_MAX_STEPS`. Price guarantees, provider-specific tokenizer/accounting, memory/storage/network quotas and customer quotas remain later work.

Cancellation fences the lease immediately; heartbeat cancels the in-flight async request. It cannot reverse provider billing or external writes. Per-step traces record sanitized status, not exception bodies/credentials. Known platform credential values are rejected from task/model input and model results; general user-secret discovery/DLP and broker lease redaction are not built. No credential value is intentionally included in a model message or tool contract. Commercial fallback remains absent, including when its reserved flag is enabled.

## Reproducible evidence

```powershell
# Disposable PostgreSQL TEST database only; trust must never be used for customer deployment.
docker run --detach --rm --name caliburn-m1-postgres --env POSTGRES_HOST_AUTH_METHOD=trust --env POSTGRES_DB=caliburn_test --publish 127.0.0.1:55432:5432 postgres:17-alpine
$env:CALIBURN_TEST_DATABASE_URL = 'postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m ruff check src tests migrations scripts
.venv/Scripts/python.exe -m ruff format --check src tests migrations scripts
.venv/Scripts/python.exe -m compileall -q src migrations scripts
$env:CALIBURN_DATABASE_URL = $env:CALIBURN_TEST_DATABASE_URL
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/demo_runtime.py
```

Tests create UUID-named schemas and clean up only those test schemas. Do not aim the test DSN at production. Without the TEST variable, PostgreSQL tests are explicitly skipped; SQLite tests alone cannot certify claim concurrency/fencing. CI provisions PostgreSQL and runs the real integration suite.

The live demo starts/stops its own local API and worker child processes, verifies the durable chat adapter, sum=5, disconnect/reconnect and contiguous SSE IDs, and saves sanitized JSON in `docs/evidence/m1-live-demo.json`. It does not open a browser or invoke a paid model. Forced crash tests terminate a real child after a tool returns but before checkpoint commit, wait for natural lease expiry, then recover using a new worker.

## Migration / rollback

Revision `0001_runtime` creates only runtime_* tables and the append-only event trigger/function, plus Alembic's version table. Leases, budgets and policy are task columns, not separate services. Initial migration schema is frozen independently of live models. Existing M0 SQLite metadata remains untouched and is not automatically executable work.

Before upgrade: stop dispatch, back up the target DB and test restoration; run `alembic upgrade head`. Before rollback: stop API/workers, preserve evidence and DB backup, then `alembic downgrade base`. Downgrade deletes the NEW runtime tables/data and should only run after explicit operator approval. Migration round-trip is exercised only in isolated test schemas. `docker compose stop` preserves the database volume; avoid `down --volumes` unless destructive deletion is intended.

## Current product status

The independent /tasks/ui console now displays actual Step/Run/event/review/budget/result state and existing pause/resume/cancel controls, with authenticated replay/reconnect and actual browser checks. See TASK_CONSOLE.md and ADR0009. Narrow independent candidate review, reviewed stdlib execution, parent repair and operator Git checkout are also implemented in their respective runbooks; those fixture-tested mechanisms are not enterprise identity or coding-quality certification.

Still open: agent-contained Git image qualification (explicit build approval pending), original-history workspace and fixed real-repository/live-model benchmark, external-write reconciliation, Capability Factory/approved registry, OIDC/Vault, evaluated memory/skills, tenant-aware model routing, embedded Open WebUI navigation and customer legal/SBOM/operations release gates. No full Codex-level or production/customer readiness claim is made.

Current migration head is0004. The 0001 notes above describe the original runtime migration; downgrading all the way to base now also destroys later workspace/policy/ancestry evidence. Prefer compatible application rollback while preserving the DB, reconcile pinned tasks explicitly, and require a separately approved backup/maintenance plan for any destructive downgrade. No schema change is required for the task console/history projection.
