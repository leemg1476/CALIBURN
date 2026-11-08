# ADR 0008 — Fixed-image Git data consumer

Status: development build/fixture qualification explicitly approved and executed2026-11-08. Actual Git container/DB/worker tests passed; customer redistribution, real-repository grants and original-history clone remain separate/open.

## Decision

Expose only repo_git_status with an optional same-task candidate_ref. It resolves immutable granted snapshot/candidate data, reconstructs a scoped Git baseline checkout and staged candidate index in an isolated temporary workspace, and returns typed actual Git identifiers/changed-file list/bounded diff/hash. It never imports/runs source, chooses caller commands, clones upstream history or writes a remote repository. The scope remains the existing file-level ACL.

Introduce separate git_inspect permission and an immutable Git image reference, explicitly registered by the operator and pinned in task policy. No existing/default workspace receives it. Data/test supervisors do not claim Git jobs. A separate Git supervisor uses the established nonroot/network-none/read-only-root/no-host-mount/resource-limited container configuration and managed cleanup. Image, scope, hashes, parent ancestry and leases are checked at enqueue/claim/heartbeat/result; live admission is rechecked before source delivery. Wrong image, missing permission and canceled/revoked work fail closed.

Extract the existing actual operator Git implementation into a stdlib-only shared module, preserving the operator checkout CLI. The fixed container driver and exact shared code are digest-pinned; no platform packages/credentials enter the Git payload. Typed output always says source_executed=false. Raw source/config/README instructions cannot authorize commands or permissions.

## License/build gate

The proposed new development image adds Git and its required Debian dependencies, unlike the existing stdlib-only runners. Dockerfile.git pins Python base digest and proposed git package 1:2.47.3-0+deb13u1, records dpkg package inventory and Git copyright, and fails unless CALIBURN_ALLOW_GIT_DEV_IMAGE=true is supplied. That flag is an operator build interlock, not independent product approval or legal clearance.

Git upstream COPYING identifies GPLv2. Debian's trixie package listing provides the proposed version and dependency/source/copyright links. Exact installed transitive versions, notices, source provision, vulnerability review and customer SBOM/distribution obligations remain release gates. After explicit user approval, the exact proposed Git image was built without version changes. The image digest, Git2.47.3,118 installed package versions and retained Git copyright are recorded in docs/evidence/git-dev-image-inventory.json. Approval covers development build/local fixture tests only. Existing operator Git use and existing Python/data/test images do not require this new build.

Primary sources read for the proposal:

- https://raw.githubusercontent.com/git/git/master/COPYING
- https://packages.debian.org/trixie/git

## Evidence and limitations

Current tests use actual DB/worker/fixed Git logic with existing operator Git and an explicitly labeled fixture replacing Docker transport. The full actual container path is a separate opt-in test requiring CALIBURN_GIT_TEST_IMAGE; after approval/build it now passed, including isolation, timeout and cancellation cases. Prior evidence files with skipped cases remain historical, not silently rewritten. Existing operator checkout is regression-tested. No host command route is exposed to the model and no live workspace grant/image is enabled.

The code is reviewable, not proof of a qualified Git image. Scoped derived-baseline Git inspection now has real image/isolation/failure proof; this is not qualification for arbitrary source execution or general original-history checkout. Original-history clone, real-repository/live-model quality benchmark, arbitrary commands/source execution, production artifact signing/registry and customer clearance remain incomplete.

## Migration/rollback

No schema migration for this Git increment; separate Factory increments have since advanced the project head to0008. New JSON grant/image policy fields default absent/disabled. Workspace implementation digests change intentionally; old pinned workspace tasks/reviews refuse changed code rather than repin silently. Preserve existing DB/evidence and reconcile old tasks explicitly. Rollback stops/disables Git supervisor, removes new grants through operator controls and deploys compatible code without dropping tables. No production grant/deployment is performed; the Git development image build was performed only after explicit user approval.
