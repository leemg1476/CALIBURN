# Host-owned Factory observations (execution binding v2)

The trusted executor now compares approved input/output vectors outside the subject's container. A successful unittest child is a prerequisite, not a sufficient result. Generated tests can monkeypatch unittest or exit0; those behaviors no longer bypass the additional host comparison. Production activation remains unavailable and all signed artifacts stay EVIDENCE_ONLY.

## Actual boundary

Owner-only plan registration binds reserved caliburn_host_oracle.json alongside the existing source/static report/test plan/image. It contains1..8 bounded typed JSON input/expected vectors, exact entrypoint and case_source bundle_declared or operator. No schema migration: the existing immutable plan.files JSON and hash bind the entire plan. Binding factory-execution-v2 adds oracle hash/count and the exact child-only test-plan hash. Vector input/expected values must match the candidate's supported closed contract schema; empty/oversized/duplicate-name/nonfinite vectors fail. No arbitrary evaluator expression or operator Python is executed on the host.

Default vectors come from the candidate's declared fixtures and are explicitly labeled as such. They are not independently authored specifications. An operator may supply additional/replacement vectors with --oracle-cases; their origin is recorded as operator, not automatically certified correct. Example JSON file:

```json
[
  {"name":"negative", "input":{"value":-17}, "expected":{"value":-34}},
  {"name":"independent", "input":{"value":1345669}, "expected":{"value":2691338}}
]
```

```powershell
docker build -f deploy/sandbox/Dockerfile.tests -t caliburn-sandbox:reviewed-tests-oracle .
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:reviewed-tests-oracle --format '{{.Id}}')
# Owner connection; source/report/test plan/image still need exact separate reviewer approval:
.venv/Scripts/python.exe -m caliburn.tool_factory.execution_control --plan-bundle BUNDLE_UUID --static-report REPORT_UUID --independent-tests C:/review/tests.json --oracle-cases C:/review/vectors.json --image sha256:REVIEWED_IMAGE
```

Development image actually built: sha256:804d513ddffadcaaee7633006cfe91339eb839667dd86e59e4a52c6c97ec15cb. It adds only the maintained stdlib invoke_runner.py to the existing reviewed-test image; no new package/license, privilege, socket, host mount or network access. Old immutable images are preserved. Customer image/SBOM/legal/security clearance remains open.

The first fresh container runs approved generated/fixture/independent unittest files. The host-only oracle metadata file is removed before delivery; the driver validates the separately bound child-plan hash. Actual child exit/output/hash are retained as isolation.child_test_run. The aggregate run names the full reviewed host+child plan; it does not pretend the host-only vectors were delivered to unittest. Withholding applies to the host-vector metadata channel; ordinary approved unittest assertions and source may naturally contain the same values, and an operator must not duplicate held-out vectors there if independence is required. The full plan is available in signed evidence for audit, not a permanent secret. Test vectors must never contain credentials.

If unittest passes, each oracle input runs in another fresh container, with only immutable source, source hash, entrypoint and that input. Neither expected value nor tests, host plan, pass flag, DB/LLM credential or authority is included. The fixed invoke driver imports/calls the subject only inside that container. Host validation treats all returned JSON as untrusted: duplicate keys, nonfinite/deep/oversized/malformed/multiple responses and extra pass fields deny. It compares exact JSON types, keys, lengths and values, so bool is not int. Zero exit without an observation is not a pass. No subject-created pass bit is accepted.

Docker configuration is independently inspected before source delivery to every container. The same independent DB-role approval, live admission/heartbeat/fencing and cancellation watcher cover the entire execution. Shared pending-create cleanup and expiry/reaping cover late creations across all phases. Each invocation is bounded by5s (driver alarm3s); the whole host+child sequence retains the existing20s execution budget plus task limits. Inherited bounded create/removal cleanup may extend the supervisor return beyond that work budget; managed expiry/reaping remains the restart backstop. Up to8 vectors may exhaust that aggregate budget rather than receive an unbounded extension. No permission or execution authority is inherited merely from a previous container success.

Host proof records the immutable vector hash, total/checked counts and PASSED/FAILED. Every PASSED result must have complete matching host proof plus matching actual successful child source/plan evidence before durable publication. Missing/partial/mismatched proof denies. A host comparison failure returns factory_oracle_failed, preserving the original child exit0/output as explicitly untrusted evidence; it never invents child exit1. Time/cancel/unknown failures cannot produce a positive qualification. New signatures/imports require complete host proof. v2 offline statement validation checks that proof and recomputes the child-only plan hash from the full signed plan. Historical v1 evidence remains historical/nonactivating; new approval cannot silently reuse an old plan or digest.

## Evidence and limits

tests/test_factory_oracle.py uses actual PostgreSQL mapped owner/verifier/reviewer/executor/signer roles and actual Docker execution for forged assertion, forged success flag and forced SystemExit0 from unittest reporting. The old child actually exits0 in each case, yet the new host check rejects the wrong value and signing is denied. A correct candidate passes two owner-supplied vectors; captured requests prove the independent expected literal and metadata are absent from both child test and invocation payloads. Actual oracle-phase revocation/timeout, bare-PASSED durable publication denial, schema-invalid vector denial and bounded hostile JSON checks are covered. General Factory recovery/cancel/replay/role/scope/signature regression remains in the full suite. Inference/principals are scripted development fixtures; PG/Docker/OS boundaries and Ed25519 are real. No paid call is needed for these security cases.

This checks finite observed JSON behavior independently of unittest reporting. It does not prove function purity, arbitrary-input correctness, covert-channel absence, complete SAST/poison/dependency/license qualification or a general adversarial Python containment theorem. A subject can still emit a matching JSON value for a known input; that matches that observation, not a proof of its internal code path. State-detection/overfitting/randomized property testing, dependency/MCP/Skill adapters, full qualification and active executable reuse remain open. Never promote solely because these tests pass.

## Rollout and rollback

No SQL migration; Alembic head remains0008. New implementation/policy digests and bindingv2 require a new task, plan, image binding and independent decision. Legacy plans without oracle metadata fail closed rather than auto-upgrade. Stop/drain granted work before deploying changed pinned code. Preserve old source/plans/receipts/images; no automatic production daemon or grant was created. Roll back compatible code/image and new admissions together, retaining evidence; do not reinterpret v2 approvals as v1 or rewrite historical records. Customer rollout still requires the existing release gates.


## Stronger new-plan profile

New plans now use host-oracle-v2 / execution bindingv3, with a fixed repeat/order/fresh-session replay profile. The earlier single-call descriptions above are historicalv2 scope, not a claim that new execution still dispatches one fresh container per vector. Current behavior and remaining gates: PROPERTY_QUALIFICATION.md/ADR0015. Historical nonactivating evidence remains readable; new publication/signatures require the stronger profile.
