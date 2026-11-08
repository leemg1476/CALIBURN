# Governed repeat, order and replay qualification

Execution binding factory-execution-v3 requires the host-oracle-v2 repeat-order-replay-v1 profile. A fresh-instance single vector can miss state carried between calls, input-order dependence and behavior that changes between sessions. The actual Factory consumer now checks all three under the existing separate owner/reviewer/executor boundaries. No source, expected-value expression or generated evaluator executes on the trusted host.

## What runs

The operator still registers1..8 contract-valid vectors in the immutable full plan. Provenance stays bundle_declared or operator; the new profile does not certify that model-declared fixtures are independent specifications. Registration always creates host-oracle-v2; old plans are not silently upgraded. The exact metadata, profile, vector hash/count, four sessions and8×N planned observations are bound to the task/request/reviewer decision. There is no client/profile opt-out field.

After approved unittest execution passes, the trusted host executes four fresh inspected containers:

| Session | Module instances | Call order inside the instance |
| --- | --- | --- |
| Forward replay1 | Fresh | vector0 twice, vector1 twice, ... |
| Forward replay2 | Fresh | same sequence |
| Reverse replay1 | Fresh | last vector twice, ..., vector0 twice |
| Reverse replay2 | Fresh | same reverse sequence |

Each invocation session receives only immutable source/hash, entrypoint and a list of inputs. The module is loaded once inside that container. Returned JSON is frozen per call before a later call can mutate a shared return object. Host-only expected metadata, test files, pass authority, DB/LLM credentials and host paths are not payload fields. The host compares every untrusted observation to its bound expected value, retaining exact JSON type/key/value checks and size/depth/nonfinite/duplicate/frame denial. Extra pass flags or a wrong number of observations fail. These are externally observed JSON properties, not proof of internal code purity.

The maintained invoke driver accepts1..16 inputs per session, uses the existing3s alarm, bounds aggregate encoded observations to32768 bytes and runs only under the existing nonroot/network-none/read-only-root/cap-drop/no-mount/resource-bounded Docker configuration. Per-session control-plane timeout remains5s; the entire child+property sequence keeps the existing20s work budget, plus bounded cleanup. This does not grant8× more time or permissions. Large/slow valid-looking plans may exhaust this budget and must not be counted as passed. Old images are preserved; the updated driver requires a newly bound/reviewed image.

Host proof records version/profile, total vector count, vectors fully validated across every session, planned/passed sessions and planned/passed observations. The `checked` counters mean successful validation, not exact number of subject calls attempted: an incomplete or malformed container can have unknown partial execution. PASSED requires all four sessions and all8×N observations. A caller cannot reduce counts, remove a replay or claim the old single-call proof against v3. Durable publication and new signatures/imports require the current profile. Historical v1/v2 nonactivating evidence can still be read/verified under its original scope; new authority cannot be inherited from it.

## Metadata poisoning guard

Independent static triage now examines every manifest string (including schema descriptions and failure modes), plus source/test text. It normalizes NFKC/case and removes Unicode format characters before selected English/Korean instruction-override checks. Metadata and source use separate iteration namespaces: a source file named manifest cannot overwrite the manifest-description check. Findings retain bounded paths, no raw directive, source_executed=false and classification BLOCKED; a real blocked report cannot become an executable plan even through the owner registration API.

This is bounded heuristic triage, not a complete multilingual prompt-injection detector. It can reject benign quoted warnings and does not recognize every paraphrase/homoglyph/encoding/context. Review/lease/scope/permission constraints remain server-side regardless of text. Candidate lookup already exposes identifiers/version/check flags rather than raw manifest descriptions; this change does not convert untrusted metadata into callable tool definitions. Production activation stays unavailable.

## Actual tests and commands

tests/test_factory_properties.py executes separately approved synthetic source through real PostgreSQL roles and Docker. A first-call-only correct function passes original unittest but fails the repeated second observation. Another function passes two forward sessions yet fails on reverse input order. Both are denied signatures. A correct candidate creates four distinct invocation containers; real publication refuses a downgraded legacy proof, a missing replay and a shortened observation counter, then accepts the unchanged genuine proof. Tests also drive four poisoned metadata variants through a real static verifier/report/plan-denial path (fullwidth English, zero-width split keywords, Korean override and source/manifest namespace collision); no candidate code is executed for those blocked cases. Models/principals remain fixtures, not enterprise identity.

```powershell
docker build -f deploy/sandbox/Dockerfile.tests -t caliburn-sandbox:property-tests .
$env:CALIBURN_TEST_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test'
$env:CALIBURN_REVIEWED_TEST_IMAGE=(docker image inspect caliburn-sandbox:property-tests --format '{{.Id}}')
.venv/Scripts/python.exe -m pytest tests/test_factory_properties.py -q -x --junitxml=docs/evidence/m3-properties-focused.xml
# Also set the existing data/Git image environment for full Docker regression:
.venv/Scripts/python.exe -m pytest -q -ra --junitxml=docs/evidence/m3-properties-pytest.xml
```

Development image actually built: sha256:cd73f5c8d9a9cff3618f2bbfe646b24c78ffe0d0ab7fbc7b2234d2f8b9067d12, same resolved Python base, no added package/license assumption. Actual driver byte-match/UID evidence and exact test counts are in DEV_PROGRESS.md and docs/evidence. No customer distribution clearance or production grant follows.

## Rollout, rollback and remaining work

No SQL migration; head remains0008. Immutable JSON plans/bindings and implementation/checker/signing-policy digests change. Require new static report, plan, task, image binding and independent review; drain/cancel incompatible granted work before code rollout. Do not mutate old receipts or relabel old proof as the stronger profile. Rollback deploys compatible code/image/admissions together and preserves evidence; no DB downgrade/deletion is required. No persistent production role/daemon is created during tests.

Finite vectors and four deterministic sessions do not establish arbitrary-input correctness, complete nondeterminism detection, resistance to harness detection/overfitting, general semantic equivalence or safe production release. Randomized/metamorphic/invalid-input suites, comprehensive SAST/dependency/license/SBOM qualification, MCP/Skill/nonstdlib execution, production signing custody/identity/release approval, activation/rollback and measured cross-task invocation reuse remain open. See HOST_ORACLE.md for the underlying host/subject boundary and ADR0015 for this decision.
