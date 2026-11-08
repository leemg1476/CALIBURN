# ADR 0007 — Scoped operator Git checkout and candidate handoff

Status: operator workflow implemented; agent-contained original-history checkout remains open.

## Decision

Keep the current file-level repository grant. An authorized operator can materialize a task's exact immutable snapshot and candidate into a fresh private task repository. Git creates a deterministic derived baseline tree/commit and performs an actual detached checkout. Candidate bytes replace working-tree files and are indexed directly from bounded blobs; actual Git produces a staged patch. Original pinned source commit remains provenance and is not falsely used as the new HEAD. No undisclosed original objects/history, remotes, hooks, submodules or credentials are cloned.

The consumer is an operator-only CLI reading the real durable task/workspace/candidate store. It checks fixed development actor/tenant, active read grant, TTL/hash/ancestry and candidate task scope before work, and rechecks scope before publication. Each invocation creates a new subdirectory; replay has identical baseline/index/diff identities without overwriting previous output. CheckoutReport is a typed versioned manifest with source/task/tenant/candidate/hash/Git identifiers and explicit source_executed=false/production_approved=false. This data export is not an execution or promotion approval.

Use the already installed trusted operator Git binary. No Git is installed into distributed agent/sandbox images and no host-process API or model tool is exposed. Only a fixed command set runs, without a shell. Isolated environment/config, empty template/hooks path, disabled fsmonitor/credentials/network protocols/automatic maintenance, no filters/hash-object transformations, no external diff/textconv, regular non-executable file modes and highest-precedence attributes preserve exact authorized bytes. Source code is never imported/run. Source .gitattributes cannot enable filters or change CRLF/encoding in this checkout.

Git object files are read-only on Windows. Failure cleanup verifies the resolved absolute generated target remains directly beneath the explicit output root, and retries readonly removal only inside that owned tree. Timeout/cancel/revoke/secret-deny leaves no partial package. No original checkout or existing output tree is removed or modified.

## Evidence and limits

Actual Git tests verify HEAD/index/blob content/staged diff, repeated isolated output, pinned original-commit import despite a dirty original worktree, excluded-file ACL, config/attribute poisoning, foreign task/principal/tenant denial, credentials, cancellation/timeout and mid-operation grant revocation. A separate-process HTTP/API/fixture worker/Docker data supervisor creates a real candidate, then a separate operator CLI produces a retained review package with independently checked HEAD/index/diff hashes.

The baseline is a reconstruction of the granted snapshot, not original-history checkout. This is an operator handoff workflow, not an agent Git command tool or code-execution sandbox. It does not complete the planned agent-contained Git workspace, fixed real-repository/live-model benchmark or production isolation. Existing host Git version/installation is a trusted operator dependency, not a newly redistributed binary or customer license clearance. No new production permission, source execution, remote write, dependency or Open WebUI branding change is introduced.

## Migration, retention and rollback

No schema migration or task/tool digest change; current head remains 0004. Generated packages contain inert source plus Git metadata and are stored only under an operator-selected existing private directory. The operator owns retention; revoking a future read does not retract an already exported copy. Demo outputs are under ignored .caliburn/checkouts and contain fixture data only.

Rollback removes/disables this operator CLI and demo while preserving existing task/candidate data. No DB downgrade, previous task repinning or runtime restart is needed. Preserve or explicitly dispose exported packages as operator artifacts; never recursively remove an arbitrary caller-supplied path. Existing model/runtime/sandbox authorization is unchanged.
