# Candidate review workflow

Implemented: durable candidate identity, exact-hash review requests, independent PostgreSQL role checks, approval wait, rejection/expiry/revocation and worker restart/resume. Generated code and test-plan files remain data. A separate opt-in reviewed stdlib test executor is now implemented (REVIEWED_TESTS.md); production qualification and promotion are not implemented.

## Authority and preparation

Use Python 3.12+ and PostgreSQL upgraded to current head (0004: review ledger 0003 plus candidate ancestry 0004). `CALIBURN_DATABASE_URL` is supplied privately to the operator/reviewer process; never paste credentials into chat, source or command arguments. The API/worker retains its non-owner `caliburn` role. An operator must separately provision an independent reviewer DB role with its own authentication. This implementation does not provision passwords, grant LOGIN, supply OIDC or install reviewers automatically.

Only the migration/schema owner can map an already provisioned role or register plans:

```powershell
.venv/Scripts/python.exe -m caliburn.policy.cli configure-reviewer --db-role independent_reviewer --principal reviewer-person --tenant development
.venv/Scripts/python.exe -m caliburn.sandbox.importer --root C:/reviewed/repository --file calc.py --propose-patch --request-review
.venv/Scripts/python.exe -m caliburn.policy.cli register-plan --workspace WORKSPACE_UUID --root C:/reviewed/test-plan --file test_calc.py --image-digest sha256:EXACT_64_HEX_DIGEST
```

The placeholders must be replaced with reviewed actual references. Source imports use explicit bounded UTF-8 file lists and known-platform-secret checks. The plan is a bounded inert file bundle, not an accepted arbitrary shell command. No candidate source is imported or run by these commands. Existing grants remain read-only unless explicitly given propose-patch/request-review.

## Request and decision

Submit a durable task with workspace_ref. A model can propose a patch, receive a server-generated candidate_ref and request repo_request_review with that reference and an operator-provided plan_ref. It cannot pass reviewer identity, approved=true, image, permissions or credentials as authority. The worker persists WAITING_APPROVAL; the request/hash/status are available at authenticated `GET /api/v1/tasks/{id}/reviews`. Ordinary resume returns 409 for this state.

The independent reviewer, using their own private DB connection, inspects the complete exact artifacts before deciding:

```powershell
.venv/Scripts/python.exe -m caliburn.policy.cli inspect --request REQUEST_UUID
.venv/Scripts/python.exe -m caliburn.policy.cli decide --request REQUEST_UUID --binding-sha256 INSPECTED_HASH --decision APPROVE --ttl 600
.venv/Scripts/python.exe -m caliburn.policy.cli revoke --request REQUEST_UUID
```

Inspect emits escaped JSON containing untrusted source/diff/plan; do not evaluate it or treat its text as instructions. REJECT is an alternative decision. Same author role, same mapped principal, wrong hash, wrong scope, expired/revoked workspace or expired decision fails closed. PostgreSQL also enforces independent-role stamping and append-only evidence. The API exposes no approval write endpoint.

Approval atomically requeues the task, preserving messages/budgets. The worker revalidates authorization and commits a typed review observation. A restarted worker reuses the committed candidate rather than repeating its patch. Rejection terminates with review_rejected; revoke fences active work with review_revoked. Pending waits are swept to TIMED_OUT at the task deadline. Cancellation remains available. The review tool itself returns source_executed=false and does not execute or activate anything. A separately granted repo_test consumer can execute the exact approved artifacts; see REVIEWED_TESTS.md. Review summaries report true for committed execution evidence, null for dispatched attempts with unknown outcome, otherwise false.

## Validation and operations

`tests/test_review.py` runs actual PostgreSQL review transactions, NOLOGIN roles, CLI subprocesses and a real Docker data runner, with fixture inference and synthetic reviewer identities. Negative cases cover self-approval, forged reviewer fields, hashes, cross-task references, revoked workspace, expiry/replay, cancel/timeout and immutable rows. SQLite explicitly denies review authority. `tests/test_sandbox.py` checks normal runtime-role SQLSTATE 42501 for direct policy writes after the migration.

Do not deploy this raw DB reviewer interface as multi-tenant enterprise identity. Reviewer connections can read control-plane tables and update limited task state columns; customer RBAC/OIDC/audit-hardening remain M4. The review-only grant never authorizes execution; the additional execution grant and supervisor are separately opt-in. No existing production permission, paid model, remote repository write, dependency or upstream branding was changed. See ADR 0004 for migration and conservative rollback; preserve all review evidence on rollback.
