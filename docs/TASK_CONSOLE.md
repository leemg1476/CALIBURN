# Task timeline console

Open `/tasks/ui` on the CALIBURN API origin. Enter an existing Task UUID and the CALIBURN service API token. Use the service token, not a provider/Vault/OAuth credential. The standalone console shows actual state/result, budgets, Step/Run history, independent reviews and SSE events. It is a single-service development UI; enterprise identity and Open WebUI embedded navigation remain unimplemented.

## Start locally

Use the existing private environment configuration and migrated PostgreSQL head0004:

```powershell
.venv/Scripts/python.exe -m uvicorn caliburn.app:app --host 127.0.0.1 --port 8000
# Separate terminal, same authorized runtime DB configuration:
.venv/Scripts/python.exe -m caliburn.runtime.worker
```

Open http://127.0.0.1:8000/tasks/ui. Optional fragment `#task=TASK_UUID` fills only the Task ID; no credentials belong in a URL. The public static page contains no task data/token. Task reads/history/reviews/controls/SSE require bearer authorization. Existing HTTP API/chat clients remain compatible.

## Behavior

Pause/resume/cancel controls follow server state. General resume is unavailable during WAITING_APPROVAL; independent decisions still use their separate authority. Terminal tasks disable controls, but their committed result/events remain visible. A run can end while an uncommitted step remains; the UI labels that step as uncommitted rather than claiming success. Input/output hashes are inspectable without returning raw step model/tool content in the history projection.

Automatic SSE reconnect sends the last accepted event cursor, deduplicates replay and refuses gaps/wrong-task frames. API restart does not lose worker-independent task/event data. Manual disconnect/reload clears the client session/token; reconnect then reads history again from the beginning. The view displays at most the last250 events; source history is not deleted. Step/run pages are bounded, with additional history loading. Raw provider/repository/event/result text stays literal, never an HTML instruction.

Token and Task content are not written by the app to localStorage/sessionStorage/cookies. The token field is cleared after connecting, while the active session holds its bearer only in memory. Disconnect/page hide aborts requests and clears that session credential. Already rendered authorized data remains a local observation; this development console does not supply enterprise device/session/DLP controls. Fetch is same-origin, no-store, no redirects or cookies, with a restrictive self-only asset/CSP policy. Known credential-bearing history metadata is refused by the server.

## History API

`GET /api/v1/tasks/{id}/history?after_step=0&run_offset=0&limit=50` returns limits/deadline, RunView records, StepView records and next_step/next_run_offset. limit is1..100; negative cursors are denied. Fixed server actor/tenant scope matches existing task APIs. No raw step arguments/messages/outputs, task lease token or approval authority is returned. No data write/dispatch happens on read.

## Verification

Browser qualification helper (isolated PostgreSQL and synthetic fixture token only):

```powershell
.venv/Scripts/python.exe scripts/demo_timeline.py
# Keep stdin open in the test terminal. Commands: restart, run, new, approval, xss, evidence, audit, stop.
```

It starts a loopback API, creates a fixture Task and runs a separate fixture worker on command. It can preserve a known fixture Task with --task UUID. The review fixture creates only an inert pending request; it never approves or executes source. Model/source/identity are mocks; PostgreSQL, browser fetch/SSE, API controls and worker checkpoints are real.

Evidence: m1-timeline-browser.json/jpg, m1-timeline-controls.json, m1-timeline-mobile.jpg, m1-timeline-review.jpg, m1-timeline-literal-result.jpg and m1-timeline-pytest.xml under docs/evidence. Actual main task completed with result42,2 model calls/1 tool call,3 steps and11 events after browser pause/resume/API restart. Narrow requested390px viewport reported375px content/client width with no horizontal overflow. HTML-like prompt/result stayed literal with zero inserted executable elements; token input was empty after connection.

Run `node --test tests/timeline_stream.test.mjs` for protocol checks and pytest for authenticated server/history regressions. `uv build --wheel --offline --out-dir .caliburn/package-check` verifies self-hosted asset packaging; it uses cached declared build dependencies, not new runtime libraries. No schema migration or upstream branding change is needed. Rollback removes these additive routes/assets while retaining DB/evidence. Full commands/results and remaining enterprise scope are in DEV_PROGRESS.md and ADR0009.
