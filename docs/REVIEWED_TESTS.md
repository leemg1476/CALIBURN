# Reviewed stdlib test execution

This is a running development workflow: immutable candidate → independent exact-hash approval → real baseline/candidate tests in separate fresh containers → durable observation consumed by the worker. Inference and reviewer identities in the recorded tests are fixtures. Existing/default deployments remain data-only. No real user candidate, reviewer credential or production execution permission was enabled by the tests.

## Build and enable deliberately

```powershell
docker build --file deploy/sandbox/Dockerfile.tests --tag caliburn-sandbox:reviewed-tests .
$testImage = docker image inspect caliburn-sandbox:reviewed-tests --format '{{.Id}}'
.venv/Scripts/python.exe -m caliburn.sandbox.test_control --image $testImage
```

This starts only the trusted operator supervisor. Its DB connection must use the non-owner runtime role. Docker access stays in that host control plane; never add a socket, administrative credentials or host filesystem mount to the API, worker or agent container. The default Compose services do not start this process. The data supervisor still requires its separate data image and never claims repo_test jobs.

Real execution authority requires a separately approved operator workspace grant, then the independent reviewer workflow in CANDIDATE_REVIEW.md. The additional importer flag is `--execute-reviewed-tests` with `--propose-patch --request-review`; do not grant it on real repositories without the user's execution authorization. Register the independent test plan against the exact `$testImage`, not a mutable tag. Supply operator/reviewer DB credentials privately in process environment, never model inputs or source.

The worker receives only `repo_test({"request_ref":"APPROVED_REQUEST_UUID"})`. It cannot select a command, image, source, test plan, secret or egress host. Task call_timeout_seconds must cover both container launches/runs (up to 40 seconds for the tool), within the overall task deadline. Default conservative limits may time out a long comparison. Grants/approval/leases are rechecked throughout; dispatch stops on pause/cancel/revoke/expiry. There is a transaction-to-dispatch race and cancellation does not undo work already run.

## Supported tests and evidence

Test-plan files use stdlib unittest, with one or more test_*.py modules and actual TestCase methods. Source lives in /work/src, plan in /work/tests; unittest imports source from the former. No requirements/pip lifecycle scripts or package registry are supported. Empty test discovery is a failure. Each run uses a fresh 16MiB noexec tmpfs, 128MiB memory, 0.5 CPU, PID32, nonroot10001, network none and read-only root. Python interprets approved text despite noexec; noexec is not claimed to prevent interpreter execution.

Per child: 10-second wall limit, 8 CPU seconds, 1MiB file size, 16KiB output and no inherited platform environment/stdin. Parent container has a kernel lifetime and host timeout/reaper backstop. Host independently checks the configured immutable image, user, mounts, network and resource configuration before source delivery. Driver/checker hashes are validated in the result. No arbitrary-code production certification is claimed.

repo_test result ok=true means the comparison produced valid evidence, not that the candidate passed. Each variant separately reports PASSED/FAILED/TIMEOUT/OUTPUT_LIMIT, process exit, bounded untrusted output and exact source/test hashes. source_executed=true does not grant production approval; production_approved is always false. Failed/fenced dispatches can have unknown execution history; review summaries return source_executed=null until committed execution evidence exists. A canceled task is not proof no code ever ran.

Recorded fixture evidence: docs/evidence/m2-reviewed-tests.json and m2-reviewed-tests-pytest.xml. The normal scenario has baseline FAILED (exit1), candidate PASSED (exit0), 4 fixture model calls and 3 tool calls. Injected interruption after the sandbox result but before the worker checkpoint reuses evidence without a running supervisor and charges the extra worker tool attempt. Tests also verify live container removal for pause/cancel/revoke, wrong image, missing execution grant, expired approval, stale controller, timeout/output overflow/process error, denied network/root writes/credential environment and withdrawn admission before a second container.

## Migration, rollback and remaining scope

The execution consumer itself needed no new schema beyond 0003. The current parent-repair version requires head 0004 and binding v3; upgrade before running this code. New digests invalidate old workspace tasks and approvals; see REPAIR_LOOP.md and ADR 0006. Existing reviewer mappings can be refreshed by an explicitly authorized operator rerunning configure-reviewer for the same principal/tenant; no new reviewer account/password or production grant is provisioned automatically. See ADR 0005 for conservative rollback preserving all evidence.

Remaining: real task-local Git checkout, iterative failed-candidate repair with new review per changed hash, fixed real-repository/live-model evaluation, signed capability promotion/registry, enterprise OIDC/tenant approval service, rootless/user-namespace/microVM and escape/supply-chain qualification. Passing the fixture comparison fulfills the stdlib execution slice, not the full M2 or enterprise acceptance criteria.
