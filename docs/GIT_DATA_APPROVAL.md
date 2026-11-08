# Git data image review and qualification gate

Current state (2026-11-08): the user explicitly approved this exact development image build and local fixture qualification. Build succeeded with the proposed Git version unchanged; actual Git Docker/PostgreSQL/worker/isolation/failure tests ran. Immutable image sha256:304e6307141490b6f48d0bb0763411b19464873e422530e7a02b1e37318f572a; git version2.47.3. docs/evidence/git-dev-image-inventory.json retains all118 installed package/version entries and Git copyright. Focused regression:34passed/10skipped,0failures, including signing/runtime ACL tests (m3-signing-git-focused.xml). Full regression is recorded in DEV_PROGRESS.md. Existing deployments have no new Git permission or host command access. No customer distribution approval is implied.

## Concrete proposed change

Review deploy/sandbox/Dockerfile.git, sandbox/git_workspace.py, git_runner.py, git_control.py, contracts/queue/store/importer changes and tests/test_git_boundary.py. The shared Git module also continues to serve the existing operator checkout.

Proposed image base: python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b (observed Debian13/trixie). Proposed package: Git 1:2.47.3-0+deb13u1, plus required Debian dependencies with --no-install-recommends. The build retains package inventory and Git copyright and is blocked by default. Actual installed dependency versions are now retained in the inventory; complete license/source/SBOM/vulnerability review remains required before customer packaging.

The [official Debian package page](https://packages.debian.org/trixie/git) identifies that version and source/dependency/copyright links. [Git upstream COPYING](https://raw.githubusercontent.com/git/git/master/COPYING) identifies GPLv2; the new binary-containing image changes the distribution dependency surface. This is the reason for requesting approval under the user's explicit license-risk gate. Development build/testing approval is distinct from production enablement, original-history repository access, source execution, external writes or customer redistribution.

## Approved development commands (executed)

```powershell
docker build -f deploy/sandbox/Dockerfile.git --build-arg CALIBURN_ALLOW_GIT_DEV_IMAGE=true -t caliburn-sandbox:git-dev .
$env:CALIBURN_GIT_TEST_IMAGE=(docker image inspect caliburn-sandbox:git-dev --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest tests/test_git_boundary.py -q
```

Do not silently change the proposed Git/base version if unavailable; inspect the failure and update the review. The operator can then deliberately start the Git supervisor with that immutable digest and create a new scoped fixture grant. Real repository/production grants remain separate actions. Existing default/data/test supervisors stay unchanged. The approved build and local fixture checks succeeded. No persistent live Git grant or real-repository/production access was provisioned.

## Runtime boundary

repo_git_status accepts only optional candidate_ref; caller command/image/permission fields are forbidden. Operator --git-image pins the workspace permission/image; task policy also pins it. Source/tenant/task/ancestry/hash/image/lease checks run in the server, not in model output. The actual fixed container should run nonroot10001, network none, readonly root, no host mounts/socket, 128MiB/0.5CPU/PID32 and bounded tmpfs/time/output. No source or hook/filter/textconv is executed. The supervisor uses existing trusted Docker control-plane access; agent/API/worker do not receive it.

Output includes actual derived-baseline Git commit/tree, candidate index tree, changed files, a bounded diff and full diff SHA256, source bundle hashes, Git version and source_executed=false. Scope remains a reconstruction of granted files, not an upstream-history clone. Tests clearly distinguish host-Git fixture transport from actual Docker qualification.

This Git increment adds no schema migration (the project now has head0008 for separate Factory evidence signing). New digests invalidate previously pinned workspace tasks/reviews, requiring explicit new tasks/approvals. Rollback disables the Git consumer/grants and keeps all task/evidence data. ADR0008 contains the decision and remaining qualification limits.
