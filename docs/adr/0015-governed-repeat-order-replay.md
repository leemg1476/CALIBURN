# ADR 0015 — Governed repeat, order and fresh-session replay

Status: implemented bounded development qualification increment; full enterprise qualification/release remains incomplete.

## Decision

Replace new single-call Factory observation plans with a fixed repeat-order-replay-v1 profile: four fresh containers, two forward/reverse sessions each and two successive calls per input inside each module instance. Expectations remain outside all subject containers. Bindingv3 and host-oracle-v2 bind profile, vector/source/image/child-plan hashes and exact session/observation counts under the existing independent owner/reviewer/executor/signing authorities. No client opt-out, SQL migration, new dependency or privilege. Existing work/cleanup/resource ceilings remain; slow/large profiles fail rather than gain unbounded work.

The host counts actual successful comparisons and rejects partial/downgraded evidence before durable PASSED publication or a new signature/import. Per-call JSON is frozen inside the disposable driver before a later call can mutate it; output remains untrusted and externally compared. Historical nonactivating evidence retains its original scope, but cannot be silently promoted to the stronger profile.

Also extend the independent static consumer to all manifest string fields and selected NFKC/case/format-normalized English/Korean override patterns. Separate metadata/source namespaces fix a concrete source-file-shadowing hole. BLOCKED static evidence cannot become an execution plan. This does not authorize source execution or claim complete prompt-injection detection.

## Evidence and limits

Real PG/Docker tests distinguish initial unittest PASS from repeat/order failures, count four distinct fresh invocation containers, deny missing replay/short count/legacy downgrade before accepting genuine evidence, and exercise four poisoned metadata→static-report→plan-denial cases without source execution. Inference/principals remain fixture identities. See PROPERTY_QUALIFICATION.md and DEV_PROGRESS.md for exact commands/cleanup/results.

This is a bounded observation profile, not an exhaustive proof of purity/generalization or malicious-behavior absence. Full property/randomized/metamorphic/invalid-input/SAST/dependency/license qualification, enterprise identity/custody, release approval and active version-pinned reuse remain unbuilt. No production registration is enabled. New checker/implementation digests require new reports/plans/tasks/reviews; preserve old records/images on rollback, never repin or rewrite historical grants. Alembic head remains0008.
