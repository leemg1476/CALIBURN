# Evidence-driven candidate repair

The worker can now revise an earlier candidate while preserving its complete bundle and immutable parent provenance. Actual tests demonstrate failed first candidate → observed assertion → parent-based repair → new independent approval → passing child. Recorded inference/reviewer/source are fixtures, not a live-model quality benchmark.

## Contract

repo_patch accepts its existing path/expected_sha256/old/new plus optional parent_candidate_ref. Without it, the source is the original workspace. With it, the server loads an immutable candidate for this exact task/workspace/actor/tenant and checks ancestry/hash/base provenance. expected_sha256 must match the parent file, not the original file. The model cannot supply parent files, a host path, new permissions or inherited approval. The output remains inert approved=false/executable=false plus a new server candidate_ref.

The child inherits all other files. Chains permit up to 32 candidates, with task model/tool/token/time/retry limits also applied; rejected/stale/failed attempts remain charged. The immutable parent relation and patch-source hash are included in review binding v3. Reusing a parent's approval request can only ever test the parent's exact source; it cannot substitute the child. Each changed candidate needs a fresh independent request/decision before execution.

## Running consumer

Follow CANDIDATE_REVIEW.md and REVIEWED_TESTS.md for separately authorized workspace/test grants and both trusted-host supervisors. Run migration 0004, rebuild both images and pin actual immutable IDs before this version. The API/worker still have no Docker, host filesystem or administrative credentials.

The runtime persists model/tool observations and resumes after each approval. A model can inspect the previous patch text and actual bounded unittest output, then call repo_patch with the parent reference, request a new review and call repo_test only after approval. Source/test content and logs remain untrusted; they cannot instruct the platform to approve or enable privileges. Real reviewers must inspect the exact child bundle, test plan, image and parent hash themselves. No real reviewer or user repository grant was provisioned by the verification run.

## Verified fixture scenario

Original total(a,b) returns a-b. First candidate returns a+b+1; actual independent tests fail with 6 != 5. The scripted inference fixture asserts that observed failure before requesting a parent-based change to a+b. The runtime then stops at WAITING_APPROVAL with a new child hash/request. The old digest cannot approve the child. After the second independent-role fixture decision, a new worker consumes the approval and actual containers show original baseline failure and repaired child success.

Normal completed scenario: 7 model calls, 6 tool calls, 2 candidates, 2 distinct approvals and 2 baseline/candidate comparisons. Cumulative token/tool budgets are preserved across waits. A rejected second request ends review_rejected; a 4-tool task ceiling ends tool_call_limit after approval without executing the child. Neither failure case produces a second comparison. Candidate ancestry source operations remain data-only until separately approved tests.

Evidence: docs/evidence/m2-repair-loop.json and m2-repair-loop-pytest.xml. Tests cover cumulative other-file preservation, stale original hash, cross-task parent including database enforcement, chain depth and migration preserving an existing root. Exact commands/results are in DEV_PROGRESS.md.

## Remaining scope and rollback

This closes the fixture-tested iterative runtime/parent-tool mechanism. Real task-local Git checkout, fixed real-repository/live-model benchmark, production sandbox/supply-chain qualification, signed tool factory/registry and enterprise identity/broker remain open. Passing the fixture does not establish Codex-level autonomous quality or full M2 completion.

0004 is additive; preserve all lineage/review/evidence on rollback. Old pinned digests and approvals intentionally fail closed; do not repin silently. Stop consumers, retain the database and deploy compatible earlier code, reconciling waits explicitly. Destructive downgrade loses ancestry and requires separate approval. See ADR 0006.
