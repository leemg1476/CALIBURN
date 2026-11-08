# ADR 0006 — Immutable candidate ancestry and evidence-driven repair

Status: implemented development workflow; real-model/repository benchmark remains open.

## Context

The reviewed test consumer produced actual evidence, but repo_patch always used the original snapshot. A repair could not inherit changes in other files, and no durable parent relationship explained which failed candidate was revised. A modified artifact must not inherit its parent's execution approval.

## Decision

Add optional parent_candidate_ref to the strict patch contract. Omission retains original-snapshot behavior. The server resolves same-task/workspace/actor/tenant candidates, validates full bundle hashes and original base provenance, follows a bounded immutable chain and supplies only the resolved files to the fixed data runner. Parent reference text from the model/runner never selects a host path or grants authority.

0004_candidate_parent adds a nullable self-FK to policy_candidates. Existing candidates remain roots. PostgreSQL also rejects cross-task/workspace/actor/tenant parents on direct INSERT. Existing append-only rules prevent mutation of parent relations. Application resolution validates at most 31 ancestors, permitting 32 candidates per chain; branches are allowed, while cycles, missing parents, changed hashes and excessive depth fail closed. Per-task model/tool/token/time/retry budgets independently bound repair breadth and failed attempts.

Candidate publication reconstructs the full child bundle from the server-resolved parent and exact patch evidence in the existing fenced transaction. Other files retain their prior changes. baseline remains the original workspace; each candidate is tested against the same independent operator plan in fresh containers. Binding v3 adds parent reference and patch-source bundle hash alongside the exact child/plan/image/control hashes.

The durable worker already consumes tool observations and chooses subsequent calls. The new parent consumer closes the repair loop: failed test → patch of failed parent → new candidate → new WAITING_APPROVAL → separate independent decision → actual retest. The old approval still names only the old source and cannot authorize the child. No auto-approval, model-created authority or approval inheritance is introduced.

## Evidence and limits

Actual PostgreSQL/Docker tests produce a failing first candidate, inspect its real assertion log, create a child, pause for a second synthetic independent reviewer decision, then pass retests. Rejection or exhausted cumulative tool budget prevents the second execution. Same-task cumulative-file preservation, stale original hash, cross-task parent (including direct PostgreSQL INSERT), 32-version bound and data-preserving migration are tested.

Inference and independent reviewer identities are deterministic fixtures. The mechanism supports iterative repair; it does not establish real-model autonomous coding quality, actual human approval, host Git checkout, real-repository benchmark, production sandbox qualification or signed capability activation. No live execution grant, remote write or customer license assumption was changed.

## Migration and rollback

Stop API/workers/supervisors, back up and restore-check the database, then run owner-only alembic upgrade head through 0004 before starting this application. Normal runtime retains no DDL/workspace-grant/reviewer authority. Existing root candidate data is preserved; new column is null. Supplied-connection tests cover migration from a populated 0003 schema on PostgreSQL and SQLite; SQLite is still unit-test-only.

Runner/tool/control/schema digests and binding v3 change, so old workspace tasks/reviews fail closed rather than silently repinning. Rebuild both data/test images from source and use immutable IDs; create explicit new task/review references. No existing workspace permission is expanded.

Preferred rollback keeps 0004 and all candidate/job/review evidence, stops dispatch and restores compatible preceding code. Changed-digest waits require explicit reconciliation/cancel/new tasks. Downgrade to 0003 destroys ancestry relationships and requires separate approved backup/maintenance; never automatically flatten or delete child history to force resume. Only disposable test schemas were downgraded/re-upgraded.
