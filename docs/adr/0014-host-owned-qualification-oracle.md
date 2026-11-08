# ADR 0014 — Host-owned observations beyond child test reporting

Status: implemented finite-vector development qualification boundary; full security/release qualification remains incomplete.

## Problem and decision

The existing Factory test driver isolated untrusted Python from host resources but classified the child from its exit status. Approved subject/test code can alter unittest assertions/result methods or exit0 during reporting. A genuine exit0 therefore cannot itself establish independent behavior correctness.

Keep the separate reviewer/executor, exact source/image/plan grants and default-off runtime tools. Add a host-owned bounded JSON vector plan inside existing immutable plan JSON; execution bindingv2 names its hash/count and the separately hashed child test subset. No SQL migration or expanded authority. Never execute source/tests/expressions on the host. After the approved child tests pass, fresh isolated invocation containers receive only source/entrypoint/input. Host code compares their untrusted JSON observations to expected values retained outside all subject containers. The child test subset also excludes the host metadata. Store actual child exit/output/hash separately from the aggregate full-plan evidence; incomplete/mismatched host checks cannot publish PASSED or receive a new signature.

Each container retains independently inspected nonroot/network-none/read-only-root/cap-drop/no-host-mount/resource-limited settings, live admission and cancellation. Total execution budget stays20s. Distinct namespace/processes prevent monkeypatching the host comparator; expected values and approval/DB/LLM credentials are absent from the invocation payload. Strict JSON parsing/type comparison denies malformed/forged pass fields. No additional library, package or license assumption is introduced; the development image adds only a maintained stdlib driver.

## Consequences

Real PG/Docker tests demonstrate actual child exit0 under three unittest-reporting attacks but rejected host observations and denied signatures. Correct independently supplied vectors pass; expectation withholding, revocation/timeout and durable missing-proof denials are tested. Inference/identity remain synthetic fixtures, not enterprise OIDC. Full evidence/commands are in HOST_ORACLE.md and DEV_PROGRESS.md.

Default vectors are candidate-declared; explicit operator vectors have recorded provenance but are not automatically correct or exhaustive. Finite matching outputs do not prove internal purity, broad generalization, absence of all malicious behavior or safe reusable release. Full property/poison/SAST/dependency/license qualification and active registry/reuse stay open. Historical EVIDENCE_ONLY signatures remain nonactivating. New plans/tasks/reviews/images are required; no silent authority inheritance or in-place approval mutation. No customer deployment or production grant is created. See HOST_ORACLE.md for rollback without destructive DB changes.
