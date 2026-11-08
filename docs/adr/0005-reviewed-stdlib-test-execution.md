# ADR 0005 — Independently reviewed stdlib test execution

Status: implemented development slice; production sandbox qualification is incomplete.

## Decision

Add repo_test with a reference-only input and a separate execute_reviewed_tests workspace permission. That permission is false by default and cannot be supplied by HTTP/model arguments. It requires patch/review grants as prerequisites. No existing grant, Compose service or production reviewer is upgraded automatically.

Keep data-only and executable consumers separate. The existing supervisor claims only list/read/search/patch. An opt-in trusted-host reviewed-test supervisor claims only repo_test using an immutable local image matching the independently approved plan. Both use the existing durable sandbox_jobs queue, task/controller leases, recovery ceilings and managed-v2 cleanup. No new table/migration or agent Docker privilege is required.

Review binding v2 includes explicit execution permission plus source, plan, image and runtime/driver implementation hashes. PostgreSQL independent review remains mandatory. Authorization is checked at enqueue, claim, heartbeat, before each variant/container source delivery, polling and result publication. Pausing/canceling/revoking fences publication and the supervisor stops the active container. There remains a bounded race between a completed authorization transaction and actual dispatch; the 200ms watcher and process cleanup minimize ongoing execution, not retroactively undo it.

Each comparison uses two fresh containers, one for baseline and one for candidate, with the same independently registered unittest plan. All source/test text arrives on stdin and is materialized only in an ephemeral tmpfs, in distinct src/tests roots. No host mounts, socket, platform environment, network, package installation or model-chosen command/image exists. Fixed Python stdlib unittest runs under non-root/read-only-root/cap-drop/no-new-privileges/seccomp/cgroup limits. Per-child stdout, file size, CPU, wall clock and container lifetime are bounded. Host code never imports candidate/test modules.

Evidence includes actual process outcome/exit code/logs, exact source/plan/image/review hashes and independently inspected container configuration. Logs are untrusted observations. Passing tests do not certify malicious source or qualify production activation. Test plans cannot be generated-and-approved by the candidate itself; only the operator-owned plan store supplies them. Registry activation/signatures/SAST/dependency/license qualification remain separate.

## Recovery and reporting

Completed container results are stored before the worker tool checkpoint and reused on an interrupted checkpoint. An uncommitted container run may repeat after lease recovery: execution is at-least-once, safe only for this no-network/ephemeral scope. Model/tool/retry/wall budgets remain in force, including charged failed worker attempts. A completed successful comparison records source_executed=true and production_approved=false. A dispatched/fenced/crashed attempt lacking committed evidence reports source_executed=null, never a false claim that execution did not happen.

## Limits and rollback

Python stdlib unittest only; no dependency resolution, arbitrary commands, Git checkout/commit, real-model quality benchmark or production arbitrary-code escape qualification. The Docker Desktop shared-kernel/container boundary is not microVM/rootless/user-namespace production certification. Reviewer roles remain trusted development DB identities. Automated role/LLM/source fixtures verify mechanisms, not actual human approval.

There is no schema migration beyond 0003. New tool/driver/control digests deliberately invalidate previously pinned workspace tasks/review bindings; create new explicitly granted tasks and new independent reviews rather than silently repinning. Existing reviewers need an operator-approved idempotent configure-reviewer refresh for sandbox_jobs SELECT; mapping/principal changes remain denied. No live role refresh was performed in development validation.

Rollback: stop both supervisors and workers, preserve tasks/reviews/jobs/evidence, revoke the explicit execution workspace or cancel pending tasks through operator controls, and deploy the preceding data-only application. Do not drop review evidence or weaken the approval checks to get a task running. No database downgrade is necessary; pending changed-digest tasks should be reconciled explicitly.
