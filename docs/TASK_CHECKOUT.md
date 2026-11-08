# Operator task Git checkout and review package

Implemented: real scoped Git checkout, candidate index and staged diff for a durable task, consumed through a separate operator CLI. This is not an agent host-shell tool or original-history clone. Full agent-contained Git workspace and real-repository/live-model benchmark remain pending.

## Run

Use Python3.12+, schema head0004 and an already installed trusted Git. Supply the DB connection privately to the operator environment. The output root must already exist, be private to the operator, be an ordinary directory and contain no symlink/junction ancestors.

```powershell
.venv/Scripts/python.exe -m caliburn.sandbox.checkout --task TASK_UUID --candidate CANDIDATE_UUID --output-root C:/private/caliburn-checkouts
```

Omitting --candidate creates the authorized baseline with an empty patch. References are resolved server-side for the fixed development actor/tenant; client arguments cannot select another principal or override permissions. Only an active unexpired read grant and matching snapshot/candidate/base/ancestry hashes are accepted. This is still single-service development identity, not enterprise OIDC/RBAC.

The CLI returns a fresh directory containing repo/, manifest.json and candidate.patch. repo/HEAD is a deterministic private baseline commit reconstructed from the permitted snapshot, not the original source commit. The original commit is recorded separately when available. Candidate files are in the working tree and index. The patch is actual Git staged diff against HEAD; it can be inspected with the disabled-external-driver flags used by the exporter. All files are regular non-executable text; original executable modes/history are not reproduced.

No original repository is cloned, fetched, checked out, changed or pushed. No original excluded-file content or metadata history enters the task repo. Source content, attributes, hooks and test logs never authorize a command or code execution. This CLI uses a fixed no-shell command sequence and isolated Git configuration/environment; it does not run source/tests. Source attributes cannot activate filters, change line endings/encoding or external diff commands. No Git, Docker socket or host filesystem grant was added to API/worker/agent containers.

## Contract and failures

CheckoutReport version task-git-checkout-v1 binds task/workspace/candidate, actor/tenant, original source commit, baseline/candidate bundle hashes, actual derived baseline commit/tree, candidate index tree, patch SHA256 and Git version. It always reports source_executed=false and production_approved=false. The manifest is evidence, not an administrator-proof signature or production approval.

Work is bounded by a 60-second overall default (maximum120) and 10-second per-command timeout, existing 128-file/64KiB-file/1MiB-bundle limits and bounded Git output. Cancel, timeout, invalid scope/hash, known configured credential or publication-time revocation denies export. Partial packages are removed only from the exact fresh validated output tree, including Windows readonly Git objects. Replays create separate directories with identical content identities. Exported copies remain operator-owned after grant expiry/revocation; manage private artifact retention accordingly.

## Actual demo and evidence

```powershell
.venv/Scripts/python.exe -m alembic upgrade head
$image = docker image inspect caliburn-sandbox:m2 --format '{{.Id}}'
.venv/Scripts/python.exe scripts/demo_task_checkout.py --image $image
```

Use an isolated development PostgreSQL DB and fixture API token for this demo. It starts/stops separate HTTP API, scripted worker and trusted Docker data supervisor, creates an unapproved candidate and then invokes a separate checkout CLI. The review package remains under .caliburn/checkouts; source is never run or approved. Evidence files: docs/evidence/m2-checkout-source-task.json, m2-task-checkout-demo.json and m2-task-checkout-pytest.xml. Inference/source are fixtures; PostgreSQL, HTTP/SSE, task persistence, Docker source operations, CLI and Git checkout/diff are actual.

No migration is required for this component. To roll back, disable/remove the CLI; preserve task/evidence data and operator packages. Current 0004 schema and existing workers need no change. Full scope/limitations/decision: ADR0007. Exact observed commands/results: DEV_PROGRESS.md.
