# ADR 0001 — PostgreSQL durable queue and fenced checkpoint worker

Status: accepted for M1 development, not enterprise security certification.

PostgreSQL is the source of truth and the queue: claim QUEUED or expired RUNNING rows using SELECT FOR UPDATE SKIP LOCKED. No Redis dependency. Random lease tokens fence stale workers; heartbeat and every step commit verify current ownership and expiry using DB time. Runs record each lease acquisition. Task state, checkpoint, step result and append-only event sequence commit together. PostgreSQL trigger rejects event UPDATE/DELETE (not an administrative immutability guarantee).

API and worker are independent processes. SSE reads persisted per-task monotonic events; Last-Event-ID is a per-task integer. Authentication remains a single server-configured development service identity, never a client user/tenant claim; OIDC/RBAC remains M4.

Model and tool calls are at-least-once after crash before commit. Completed steps are never replayed. Only reviewed read-only built-ins are admitted; side-effect tools are forbidden until an idempotent executor and reconciliation contract exists. Recovery consumes additional call/token/cost reserves; retry ceiling survives restart. Pending calls are not evidence of success. Cancellation revokes the lease immediately and heartbeat cancels local async work; it cannot reverse an external operation.

Token accounting is conservative UTF-8/JSON byte reservation plus framing allowance and output ceiling; cost is a configured conservative per-call reservation, not billed usage. Unknown commercial pricing must fail configuration rather than claiming a monetary guarantee. Wall deadline starts on first claim and continues through pause/recovery. Terminal states cannot be resumed. WAITING_APPROVAL never implies model self-approval; no approval execution path exists in M1.

Migration: new runtime_* namespace, no automatic SQLite import. Rollback requires stopping API/workers and preserving a DB backup before Alembic downgrade, which deletes only new runtime tables. M0 SQLite remains untouched. New dependencies SQLAlchemy/Alembic/psycopg need exact-version SBOM review before customer redistribution; license assumptions are provisional.
