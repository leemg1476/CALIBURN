# ADR 0002 — Isolated workspace data operations behind a durable queue

Status: implemented for development read/patch workflows; not production approval for untrusted code execution.

## Decision and running consumer

Extend durable tasks with an optional server-registered workspace reference. A workspace is a bounded immutable UTF-8 file bundle, actor/tenant scope, canonical SHA256, read/propose-patch permissions, provenance and TTL. Task submission accepts only the opaque reference; no client supplies a host root, Docker option, identity or image. The runtime pins the snapshot and workspace-tool source revision in task policy. Existing tasks without a reference keep M1 behavior and idempotency hashes.

A model tool request becomes a sandbox_jobs row bound to task, step and current task lease token. Runtime workers never import a host executor or run Docker/subprocesses. A separate trusted operator supervisor polls requests and launches one fresh container per request using an explicitly selected immutable local image ID. PostgreSQL retains input/result checkpoints. Duplicate step dispatch reuses the persisted request/result; expired controller leases are fenced. Controller recovery is bounded by both the task retry ceiling and a hard three-attempt maximum. Task cancellation/pause, deadline, workspace expiry/revoke or superseded controller ownership prevents result commit and stops the local operation.

The implemented consumer is repo_list/read/search and inert repo_patch through the actual task worker. The demo uses separate API, worker and supervisor processes, real PostgreSQL/HTTP/SSE and real task containers. Inference is a scripted fixture. Patch candidates carry base/candidate hashes and diff, approved=false and executable=false. No model-generated candidate is imported, registered, tested or executed.

## Isolation

The fixed runner is stdlib-only and does not include platform modules, credentials, Git, package managers for task use, arbitrary commands or source loaders. It treats source as text. Docker create uses network none, read-only root, user 10001:10001, all capabilities dropped, no-new-privileges, default seccomp, memory/swap 128 MiB, 0.5 CPU, PID 32 and nofile/nproc limits. Only a bounded noexec/nosuid/nodev /work tmpfs is writable. There are no host mounts or Docker socket. Image pulls are disabled at request time. The supervisor independently inspects the created container settings before delivering source; result contracts, size and runner-source SHA256 are checked before persistence. Containers have a 25-second process lifetime in addition to controller timeout/cleanup. Cancellation waits for Docker creation to settle before addressing only its generated container name for removal.

The supervisor is a host control-plane program with operator-owned Docker access. It is not an agent and is not mounted into agent containers with a socket. It must not be enabled as an unrestricted model tool, public API or socket-proxy fallback. This change does not grant Docker or administrative DB permissions to the API/worker. The Compose agent services remain unchanged in that respect; the supervisor is not auto-installed or daemonized.

## Workspace source and authorization

The operator importer reads an explicit bounded file list from a selected local directory or full immutable Git commit. Git mode reads local objects, disables hooks/fsmonitor/credential helpers, pathspec globbing, replacement objects and lazy fetch, and rejects partial clones, includes, alternate object stores, metadata links and symlink/submodule entries. It neither clones nor fetches. Git is an existing operator-host dependency, not added to the agent/runner image. Uncommitted file changes cannot alter a pinned Git snapshot. Plain directory import requires an operator-controlled quiescent directory; it is not an adversarial concurrent-filesystem importer.

Runtime PostgreSQL role caliburn loses INSERT/UPDATE/DELETE on sandbox_workspaces during migration, so the existing broad development default privileges cannot authorize its own workspace grants. Register/revoke require an operator connection, never model-originated requests. Development still has one fixed service actor/tenant; this is not OIDC or a production service-identity permission system. Supervisor permissions and credential brokering need M4 hardening.

## Migration and limits

0002_workspace adds nullable runtime_tasks.workspace_ref and two new tables; existing M1 rows remain valid. No host checkout or source file is changed. Stop processes and preserve a DB backup before deployment. Rollback to 0001 drops only the new workspace/job data and column; stop processes and deploy the previous application version as well. Never downgrade a customer database without explicit approval.

Limits: 128 text files, 64 KiB per file, 1 MiB bundle, 240-character portable relative paths, bounded read/search/patch input and output. Project dotfiles such as .github and .gitignore can be explicitly granted; credential/SCM-private paths, traversal, links and oversized/binary inputs are denied. General DLP is not claimed. Known platform-secret checks inspect decoded JSON strings, including tool argument strings, and supervisor outputs before persistence.

## Work still required

Actual Git checkout inside a task workspace, approved test execution, bounded repair against independent test results, real-repository benchmarks and approved external writes remain M2 work. The current data-operation slice is not a replacement for those goals. Rootless/user-namespace/microVM deployment, hostile native-code escape qualification, production cleanup/reaper behavior under prolonged Docker-daemon failure, service identities, independent approval/signing and customer SBOM/license gates remain unresolved. Docker Desktop cgroup/seccomp evidence does not certify a production sandbox for executing arbitrary generated code.
