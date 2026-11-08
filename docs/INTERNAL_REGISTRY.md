# Working internal Tool registry

The development runtime can now reuse a generated Tool across unrelated tasks. This is an executable pure-JSON tier, not production approval or the general MCP/Skill registry.

Implemented: schema0009; scoped immutable version signatures; active-head selection; automatic task pinning; typed model-visible tool contracts; durable isolated invocation queue; output checks and quarantine; lease recovery; revoke/rollback; authenticated `/api/v1/registry` and `/api/v1/registry/metrics`.

Set `CALIBURN_ALLOW_REGISTRY_INVOCATION=true` on API/Worker to let new tasks select already approved internal versions. `capabilities:null` selects up to eight eligible tools, `[]` selects none and a list selects exact names. The client cannot activate candidates or grant this server flag. Production registration remains unsupported. Disable the flag to stop new pins; revoke a release to stop existing pins too.

## Real-model demonstration

The live experiment used actual paid gpt-6-luna calls, PostgreSQL persistence, a separate verifier/executor process, real Docker and Ed25519. Sales data is synthetic. The first generated source had a real ABI error: `run(data)` versus declared keyword `records`. Static ABI inspection rejected it without executing it. The model produced immutable1.0.1 with `run(records)` and passed the supported profile.

The corrected Tool passed five unittest cases and sixteen host-checked observations across four fresh invocation sessions. After the user's exact-source approval and conditional reuse approval, the internal1.0.1 release was activated for at most one hour. Two new real-model tasks independently selected the same registered function, returned correct totals14500 and950, and completed in7.688s and6.844s. Both used two model calls and one actual isolated tool call, without regenerating source. The generation13.937s, repair11.156s and qualification12.266s are separate elapsed measurements, not a standardized model benchmark.

An additional real-model comparison task independently invoked the registered Tool twice, then add_numbers on the two actual totals to report the difference13550. It completed in12.389s (persisted DB creation-to-update elapsed),3model/3tool calls. This demonstrates a multi-stage business workflow using the generated capability and a curated tool together. Evidence: `evidence/live-business-comparison.json`.

Evidence: `evidence/live-factory-reuse.json`; frozen inert source/manifest under `evidence/live-sales-tool/`. Final cumulative paid usage including earlier smoke tests and comparison:20requests/24596input+output tokens, below100/50000. The earlier two-task proof records the truthful intermediate snapshot17/21648. These are API-reported tokens; the configured per-call cost is a budget reservation placeholder, not an invoiced dollar figure.

## Reproduction and operation

Use the existing PostgreSQL deployment; run `python -m alembic upgrade head`. Build `docker build -f deploy/sandbox/Dockerfile.tests -t caliburn-sandbox:registry-tests .` and retain the inspected immutable image ID. Runtime may not receive a Docker socket. The trusted host executor runs `python -m caliburn.tool_factory.release_control --image <immutable-id> --once` under a configured executor database role; a continuously operated executor can omit `--once`.

Release control supports `--configure-role`, `--request-artifact`, `--inspect`, `--decide --binding-sha --decision --internal-license-approved`, `--activate --private-key`, `--rollback` and `--revoke`. Activation CLI accepts encrypted PKCS8 and a password from CALIBURN_SIGNING_KEY_PASSWORD; never place that password in model inputs. The demonstration used an ephemeral host-memory key and registered only its public half. This is not production KMS custody.

Live scripts explicitly require `--allow-paid`: `scripts/live_generate_capability.py`, `scripts/live_prepare_qualification.py`, `scripts/live_complete_reuse.py`, `scripts/live_compare_reports.py`. They use the shared absolute ledger `.caliburn/live-llm-budget.json`, max100requests/50000tokens, and read `.env.apikey` only in the trusted model gateway. Preparation never executes the candidate. Completion consumes the previously bound review request once; it is an experiment continuation, not an idempotent deployment command. Comparison supports `--task-id` to export an existing completed task without repeating paid inference. The current proof includes the user's actual approval. Future internal-demo approvals can be made by the delegated development agent with truthful actor/scope records.

## Validation and limits

Registry tests use fixture model output and fixture principals; PostgreSQL migrations/roles, signatures and Docker execution are real. The separate live evidence uses actual model output. See DEV_PROGRESS for terminal test counts and exact commands.

Supported source has one `.py` file, required keyword parameters matching the closed manifest, primitive JSON computation, no imports/attributes/dependencies/permissions. Replay vectors are finite correctness evidence. AST checks and Docker are not an arbitrary-code escape certification. OIDC, Credential Broker, customer license clearance, production key custody, broad workload quality benchmarks and long-term reliability scoring remain open. Existing Open WebUI branding and dependency assumptions are unchanged.

Migration/rollback is recorded in ADR0016. No database downgrade is needed to disable or revoke this development feature.
