# Factory independently reviewed sandbox tests

Implemented: operator plan → runtime review request/wait → independent PostgreSQL reviewer decision → runtime resume → separate host executor → actual container tests → immutable result → resumed model/tool loop. This is an opt-in Python stdlib tool qualification subset, not production registration.

Requirements before a plan can exist: immutable source bundle; same-scoped current independent static report with REVIEW_REQUIRED classification; tool kind; no declared dependency installs or permission requests. BLOCKED source, MCP/Skill kinds, network/file/secret grants and dependency installation remain denied. An unflagged static report is incomplete evidence, not permission. Source stays QUARANTINED after all outcomes.

An operator supplies an independent test bundle as a safe JSON file mapping relative test paths to text. The plan combines it with model-generated tests and a fixed strict type/value comparison of declared fixture calls. Entrypoint must be a Python function accepting the fixture object's keyword arguments and returning the declared JSON-shaped expected result. Local module imports may work through /work/src; arbitrary package/MCP/Skill execution is not supported. Plan source is only materialized as text on the host, never imported/executed there. All generated test/subject code runs only after a separate execution decision inside the disposable container.

Operators provision separate runtime/reviewer/executor credentials outside the agent. Using an owner connection only for mappings/plans:

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --configure-role factory_execution_reviewer --kind REVIEWER --principal independent-factory-reviewer --tenant development
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --configure-role factory_sandbox_executor --kind EXECUTOR --principal factory-sandbox-service --tenant development
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --plan-bundle BUNDLE_UUID --static-report REPORT_UUID --independent-tests path/to/reviewed-tests.json --image sha256:APPROVED_LOCAL_IMAGE_ID
```

Use existing approved local reviewed-test image, not a tag/mutable/latest reference. No image/package/Git install is part of this increment. Owner credentials stay outside runtime/verifier/executor environments and models. These deployment commands are instructions; tests only create temporary synthetic NOLOGIN roles in disposable PostgreSQL, not persistent customer roles.

The API needs CALIBURN_ALLOW_FACTORY_EXECUTION=true to grant both new tools to NEW Tasks; default false in config/example/Compose. Existing task permissions do not grow. Clients cannot submit this flag, identity or policy. The task asks capability_request_execution(plan_ref); SSE emits FACTORY_EXECUTION_REVIEW_REQUESTED and state WAITING_APPROVAL. General resume/approve HTTP calls cannot approve it. GET /api/v1/tasks/{id}/factory-execution-reviews provides up to20 scoped hash/binding/status/dispatch summaries without raw source or lease tokens.

Using a separately mapped reviewer connection:

```powershell
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --inspect REQUEST_UUID
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --decide REQUEST_UUID --binding-sha EXACT_INSPECTED_SHA --decision APPROVE
# Or --decision REJECT; to invalidate a decided request:
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --revoke REQUEST_UUID
```

Inspect emits exact untrusted source, static report and reviewed plan/binding; text is not an instruction or authority. It reports dispatch_attempted, not a guarantee that interrupted source did/did not execute. Reviewer identity cannot equal source/request/plan/static author or Task actor; mapped roles cannot have runtime Task/candidate mutation privileges. Reviewer only appends decisions, without Task writes. The next runtime worker claim revalidates and queues/fails the waiting Task. Expired/disabled/revoked/mismatched inputs fail closed. Plans/bindings cannot be changed in place; changed code/tests/image require a new plan/request/decision.

After approval, the worker can call capability_execute_tests(request_ref). Separately start the trusted host executor with ONLY its mapped executor connection:

```powershell
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --image sha256:APPROVED_LOCAL_IMAGE_ID
# For a one-shot consumer use --once.
# Owner-only mapping disablement:
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --disable-role factory_sandbox_executor
```

The supervisor owns Docker on the trusted operator host; no socket, host filesystem, admin/cloud credential or process-execution tool is attached to an agent container. The inherited fixed image/driver enforces nonroot/read-only-root/network-none/cap-drop/seccomp and memory/CPU/PID/tmpfs/wall/output limits. It inspects actual Docker configuration and checks admission before sending source, during execution and before persisting results. Cleanup/reaping uses the existing managed-v2 expiry lifecycle. Offboarding must also revoke/rotate DB credentials/SELECT grants as needed; disabling the mapping alone stops privileged actions, not database confidentiality access.

Actual evidence: PASSED, FAILED, TIMEOUT or OUTPUT_LIMIT with exit code, bounded untrusted output, exact source/plan hashes, image/request/binding and executor DB role. Transport failure can have unknown source execution; missing results do not mean no source ran. Successful transport can contain FAILED tests. Every positive execution report has production_approved=false, security INCOMPLETE and license UNREVIEWED. A passing unittest child can be tampered with by malicious approved Python; this is not full anti-tamper/security certification. Model-generated tests are not automatically trusted independent specifications. No signing, active registry or qualified callable reuse is implemented.

An actual exit73 worker crash test dies after persisted test evidence and before the tool checkpoint; replacement worker waits for natural lease expiry and reuses the same job/result without another container dispatch, charging the replayed tool attempt. Other tests cover real independent executor OS process, wrong candidate failure, time/output exhaustion, running-container revoke/cancel/pause cleanup, cross-actor/tenant/plan/image denial, unrelated wait nonstarvation, server-only flag and DB-role write denials. Models/reviewer principals are synthetic fixtures; DB/OS processes/Docker/test exit evidence are real. See docs/evidence/m3-execution-{passed,failed}.json and JUnit evidence; these are not live-model/real-repository quality benchmarks.

Migration0007 adds six tables and guards/grants; no existing deployment is automatically migrated. Rollback should retain evidence and drain/stop digest-pinned work. Explicit backed-up downgrade to0006 deletes execution records/mappings and needs operator approval. Existing candidates/static reports/runtime events remain; independently provisioned DB roles/credentials need separate offboarding. See ADR0012/DEV_PROGRESS for exact tested commands and current scope.

Migration0007 also pins13 shared/new Runtime/Policy/Factory stored-trigger lookup paths to the application schema with pg_temp last (pg_catalog implicitly first, invoker identity preserved). Disabled-mapping temp-table attacks are now denied for execution review, static verification and repository review. No privileges are added by this hardening. Downgrading only execution tables retains shared trigger hardening.
