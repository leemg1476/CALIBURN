# Security requirements and threat model

Factory proposal slice (ADR0010/schema0005): source/test/skill text remains inert even when syntax/fixtures are valid. Requested permissions/secret handles grant no rights. There are no production candidate invocation/promotion/signing routes. ADR0012 now adds a separately reviewed, default-off stdlib sandbox-test executor; static/proposal results alone still confer no executable authority. PostgreSQL records are append-only, author/scoped to live permitted Task/Step; service queries check actor/tenant and configured known-secret values. The development fixed principal and trusted DB boundary are not customer OIDC/RLS isolation. Model-generated tests/SBOM/licenses remain unverified declarations. Git image approval remains separate and pending.

## Trust premise

The LLM is a planner/suggester, **not a trusted actor**. User requests, retrieved web pages, git source code, test logs, MCP tool descriptions, agent-authored scripts and memory candidates can contain prompt injection. A model cannot grant itself new privileges.

## Credentials and authorization

- Target: OIDC identities and delegated OAuth per tenant and person; service principals for automation. Avoid platform-wide 'master tokens' in a tool context.
- Store third-party secrets using OpenBao or other reviewed KMS/vault with encryption at rest, audit, lease/rotation/revoke.
- Model-visible tool contract uses `credential_ref`/`grant_id`, *never* credential values. Tool runner resolves a short-lived token server-side after authorizing task+actor+action+resource.
- Scope grants to the smallest possible object and verb, with expiry and separate approval for side effects.
- Redact tokens from exception messages, stdout, traces, tool response snippets and artifacts. Enforce max log size, secrets scanners and least-retention defaults.
- No session-cookie forwarding from UI to third-party tools. Do not accept client-supplied role/tenant IDs without server-side verification.
- Production must have explicit deny paths for absent identity, expired grants, wrong tenant, wrong tool digest, unauthorized egress and revoked OAuth grants.

## Tool execution policy

- Static tools must declare `id`, `version`, `digest`, JSON schema for arguments/output, network domains, file scopes, secret scopes, side-effect class, timeout, quotas and owner.
- Model-proposed new code remains `CANDIDATE` and cannot be imported/executed by API/gateway runtime.
- Generated MCP server is tested against fake external services in isolated runner; no unrestricted package installation or registry access.
- Promotion needs independent policy approval, test evidence, immutable digest and active tenant policy. Do not let candidate-generated tests alone certify safety.
- Install sandbox measures at host/container/orchestrator level, not just prompt instructions or AST blacklists. Use non-root, user namespace/rootless runtime, seccomp/AppArmor, cgroups, read-only filesystems, per-task temporary volumes and egress proxies.
- Allow outbound network only to explicit tool hosts. Block cloud instance metadata endpoints and internal control plane addresses. Ensure DNS rebinding and proxy bypass protection.
- Separate read-only repo-inspection phase from write/patch phase. Git push, PR creation, publish and deploy require explicit approval and separate scoped credentials.

## Supply chain and licensing

- Before publishing tool: SBOM, pinned dependency resolution, package source policy, SAST and dependency/vulnerability scanning. Require ownership and a license allowlist.
- Store signed artifact hash, runner image digest, test fixture hashes and final permission manifest.
- Review both source and transitive dependencies before enabling customer-facing features.

## Operational controls

- Every task has budgets: tool calls, LLM tokens, wall time, workspace size, network bytes, money and maximum retries.
- Cancellation stops new tool dispatch; side-effect tools require idempotency keys and reconciliation; never assume cancellation reverses a committed write.
- Persist a monotonic event sequence; audit includes policy grants/denials and artifact digests, not secrets.
- Single-service API token in this bootstrap is a development adapter, **not** production multi-tenant auth.
- Fixture model and SQLite task store are for local validation only.

## Must-fail tests

1. Cross-tenant task read, trace read and tool version access.
2. Prompt injection in README, web page or tool output asking for vault secrets.
3. Tool candidate attempting to self-approve and call internal admin endpoints.
4. Exfiltration via DNS, HTTP, callback URLs or malicious dependency lifecycle scripts.
5. Replayed approval token or changed artifact hash after approval.
6. Runner timeout/kill midway through an external side effect.
7. Commercial fallback disabled while the local provider fails.

## Implemented M1 security boundary — 2026-11-08

Durable tasks use PostgreSQL, fixed server-owned development actor/tenant and a static reviewed read-only tool allowlist pinned by source digest. HTTP task contracts reject user-supplied principal/tenant/policy fields; repository/model text cannot authorize a tool, approve itself or select credentials. Known configured platform secret values are rejected from task/model inputs and worker model outputs. This is not a general-purpose DLP or credential broker.

Cancellation/pausing fences lease commits and stops subsequent dispatch. Crash retries are at-least-once for uncommitted read-only calls; no exactly-once external-write guarantee exists. Events reject PostgreSQL UPDATE/DELETE via trigger, without claiming administrator-proof immutable audit. Token and money limits use conservative reservations, not provider billing certification.

Compose separates administrator/migration DB credentials from a non-superuser API/worker role; internal network denies external egress. No Docker socket, privileged host mounts, shell tool or generated code execution exists in the agent process. SQLite concurrency is not a supported deployment guarantee. M2 sandbox controls, M3 approval/promotion and M4 OIDC/tenant/vault tests remain release requirements.

## M2 data-runner evidence

Typed workspace tools now run in a fresh non-root/network-none/read-only-root container with no host mounts/socket/credentials, bounded tmpfs/memory/CPU/PID/time and independently inspected settings. The runtime cannot choose a host path, Docker flags or image; an operator selects an immutable reviewed local image. Untrusted file contents are text only. Candidate patch output stays approved=false/executable=false and cannot run or publish itself. SQLSTATE 42501 regression checks verify the runtime DB role cannot mint/update/delete workspace grants after migration.

Workspace scope/expiry/revoke and task/controller fencing are rechecked for queued dispatch, polling, heartbeat and result commit. Known platform-secret checks now inspect decoded strings, including escaped JSON tool arguments, and sanitize supervisor results before persistence. General DLP, production service identities, native-code escape qualification and generated-code approval/execution remain release blockers. See ADR 0002 and M2_WORKSPACES.md; a successful data runner is not a production arbitrary-code sandbox certification.

## Verified lifecycle correction

Shielding only subprocess communicate after handle assignment was insufficient: a legacy test container appeared later in Created state. The complete create/spawn handshake is now owned across cancellation; new managed-v2 creation persists expiry before start. Startup/periodic cleanup is limited to expired marked/generated-name instances with no host data/network; unmarked, legacy, malformed or active objects are preserved. The reaper lives only in the trusted host control plane and requires a running/restarted supervisor or explicit operator action. No arbitrary-code execution or agent Docker permission was enabled.

The optional Open WebUI smoke profile is loopback-only, auth-disabled, fresh-volume and fixture-only. It is not a tenant/enterprise security profile. The target host required a fixed operator loopback transport because internal-network ports were not published; agent network isolation was preserved. Actual UI evidence does not certify production ingress or license clearance. See ADR 0003 and OPEN_WEBUI_SMOKE.md.

## Opt-in reviewed test execution

ADR 0005 adds a separate trusted-host consumer for repo_test. Default/existing grants remain data-only. Execution requires an explicit operator execution grant, independent PostgreSQL reviewer decision on exact source/plan/image/implementation hashes, live task/controller leases and repeated authorization before source delivery, between variants, during execution and before results. No generated-source import occurs in the API/worker/host. Baseline and candidate run in separate fresh network-none/read-only/nonroot/no-host-data containers; fixed stdlib unittest only, no package installation or caller-chosen commands. Child environment contains no platform credentials; output/file/CPU/wall/container resources are bounded. Actual network/root-write/credential-environment and cancel/pause/revoke tests pass against Docker. This is development fixture evidence, not production arbitrary-code/microVM escape or supply-chain certification. Test logs are untrusted and passing tests never activate a tool. A dispatched attempt lacking a committed result has unknown execution status, not a guarantee that no source ran. See REVIEWED_TESTS.md for the transaction-to-dispatch race and remaining release gates.

Parent-based repairs (ADR 0006) inherit source text, never approvals. References require the exact task/workspace/actor/tenant, immutable full-bundle/base hashes and bounded ancestry. PostgreSQL denies cross-scope parent insertion; existing append-only rules protect links. A child binds its own source, parent and patch-source hashes and stops for new independent approval. Fixture tests prove old digest rejection, no second execution on rejection/exhausted budget, stale-base/cross-task denial and bounded chains. No new execution permission or secret exposure is introduced by the repair operation.

Operator checkout (ADR 0007) is a read-authorized inert export, not an agent command surface. Only scoped snapshots/candidates enter a fresh private directory; original source/history/remotes are untouched. Fixed Git commands use no shell, external diff/textconv, filters, hooks, credential helpers, inherited configuration or network protocol. Highest-precedence attributes preserve exact bytes. No source runs and no candidate is approved. Grant/TTL/hash/ancestry and known configured credentials are checked before work and before publishing. Partial cleanup resolves and verifies only the generated subtree, with a Windows readonly-object retry limited to that subtree. Already exported copies remain subject to operator retention; revocation is not a remote delete of copies. Existing host Git is an operator trust dependency, not a new binary or host privilege in agent images. Task-local agent Git execution remains a separate unbuilt qualification boundary.

The independent task console (ADR0009) adds no public task data or identity authority. Static assets are inert/self-hosted/no-store/nosniff with restrictive CSP and frame blocking. Data/control/history/review/SSE still require the existing bearer. The client uses same-origin no-store requests without cookies/redirects and keeps the entered service token only in the active JS session, clearing the field and dropping the session token on disconnect/page hide. No browser storage or LLM message receives it. All untrusted task/result/event/review data is rendered through textContent; actual browser injection fixtures produced zero script/img elements. History omits raw step content/leases, checks fixed principal/tenant scope and refuses known credential-bearing metadata. Resume is disabled and server-denied for WAITING_APPROVAL; the UI cannot approve. This is still development service-token identity, not production OIDC/session/device isolation.

## Factory static triage boundary

Default-off capability_check submits only inert metadata work. Independent configured verifier must differ from request/source authors and have no runtime Task/candidate mutation privileges. Role offboarding, added runtime writes, tenant/hash/lease/deadline mismatch and terminal task deny publication. Runtime SQL cannot create reports/configure verifier mappings; PostgreSQL also rejects execution/activation/PASS/security-verification claims and report mutation. Static heuristics are incomplete and never authorize execution or production release. No host execution, dependencies, network or Docker authority is added. Parsing is bounded, not hard process-isolated; existing executable review gates remain separate. See ADR0011.

Verifier CLI startup also sanitizes settings/DSN parsing and disposal errors; a malformed synthetic port regression asserts that configuration values do not echo into diagnostics. This is specific tested hardening, not proof of a universal secret scanner.


## Factory execution-only boundary and stored trigger lookup hardening

ADR0012/schema0007 implements separate Factory reviewer/executor mappings, owner-created immutable plans, current hash/static-report/scope/image checks and expiring/revocable decisions. Reviewers append decisions but cannot mutate Tasks. Runtime owns wake/resume and cannot forge decisions or executor results. A separate trusted host executor owns Docker; agent processes only submit/poll metadata. No agent socket, host root mount, cloud/admin credential or network egress is added. Source/test payloads are delivered only after independent review plus live admission checks; cancellation/revocation interrupts and removes managed containers. Unknown interrupted execution is never reported as definitely not executed. Results always keep production_approved=false/security INCOMPLETE/license UNREVIEWED. Test code/subject can tamper with their own test child; passing process status is not complete anti-tamper qualification.

A real negative SQL test reproduced disabled-reviewer authorization restored by a caller-owned temporary mapping table. Migration0007 pins13 existing/new Runtime/Policy/Factory trigger functions to the trusted application schema with explicit pg_temp last; pg_catalog stays implicitly first and current_user is preserved (no SECURITY DEFINER or privilege expansion). Equivalent Factory execution, Factory static and repository-review temp-map attacks are denied by actual PostgreSQL tests. Shared function hardening is retained if only execution tables are downgraded. Direct DB services/owners remain trusted, not customer RLS/compromised-host isolation; production security qualification remains open.


## Signed evidence boundary (0008)

Independent signer authority cannot be inherited from source/runtime/static/reviewer/executor roles. Only public keys are persisted; encrypted operator private keys are opened solely by the signer process. Scoped API/lookup reads perform actual Ed25519 verification plus live key/mapping/review revocation and source/checkpoint consistency. SQL guards provenance/immutability but does not verify cryptography; raw DB rows are untrusted until verified. Offline verification uses a separately trusted public key and cannot attest live revocation. Every signed result remains EVIDENCE_ONLY/noninvokable; full security/license/anti-tamper/release qualification remains open. See SIGNED_EVIDENCE.md. Explicit ignored API-file loading separates credential headers from model bodies; ordinary tests never load developer keys. The50,000/100 development ledger is not an account-wide enterprise quota or vault.


## Child-report tamper versus host-owned observations

Approved subject/generated tests can monkeypatch unittest or force exit0; a passing child remains untrusted behavior evidence. The v2 Factory consumer additionally compares bounded typed JSON observations in the host control plane against owner-bound vectors, with fresh networkless/nonroot containers per input. Host expected vectors/approval/DB/LLM credentials and pass flags are never invocation inputs; the initial child plan also excludes host-only metadata. Strict JSON structure/depth/size/type checks and live admission/cancel cleanup apply. Durable PASSED publication and new signatures require complete matching host proof and actual child source/subset-plan evidence. Historicalv1 signatures remain EVIDENCE_ONLY. Finite matching outputs cannot prove purity/generalization/absence of covert channels or all malicious code; full qualification and production activation remain blocked. HOST_ORACLE.md/ADR0014 distinguish candidate-declared versus operator vectors and exact limits.


New bindingv3 requires complete fixed repeat/order/replay proof; single-call/partial/downgraded counters cannot publish new success or receive a new signature. Host profile inputs remain data; no generated evaluator runs on host. Selected English/Korean manifest overrides are checked after NFKC/case/format normalization across every manifest string, without source-file shadowing. This remains heuristic, not complete SAST/prompt-injection assurance. Supported-tier release must combine these observations with an explicit source/dependency/license profile and a distinct release decision; no active registry is enabled yet. PROPERTY_QUALIFICATION.md/ADR0015.
