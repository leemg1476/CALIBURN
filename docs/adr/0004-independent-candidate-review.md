# ADR 0004 — Exact-artifact independent review ledger

Status: accepted for the development workflow; candidate execution remains disabled.

## Context

The data-only patch tool produced an inert diff but had no durable candidate identity or working review consumer. A client `approved` flag or model-produced approval cannot authorize execution. Review must survive worker replacement and bind the precise scope that was inspected.

## Decision

Persist candidate bundles atomically with fenced sandbox results. Migration 0003 adds candidate, operator-owned test-plan, reviewer mapping, request, decision and revocation tables. Candidate/plan/request/decision/revocation rows are append-only in PostgreSQL. Candidate and request authors are stamped from current_user in database triggers, not caller JSON.

An explicitly granted repo_request_review call binds task/actor/tenant/workspace, base and candidate bundle hashes, plan hash, immutable image reference and tool implementation digests. It moves the actual task to WAITING_APPROVAL before reserving a tool attempt. A separately provisioned PostgreSQL reviewer role must map to a different principal and differ from both author roles. The agent role cannot write plans, mappings, decisions or revocations. The general task resume endpoint cannot resume approval waits.

The reviewer CLI inspects the exact untrusted source/diff/plan and requires the binding digest for APPROVE or REJECT. Decisions expire, cannot replay, and can be revoked. The decision and task requeue/failure event commit together under a task-row lock. A new worker rechecks the complete binding, scope, expiry, mapping and revocation before consuming the result. Budgets and previous patch results are preserved.

## Limits and consequences

This is an operational review/pause/resume workflow, not a test executor, signature service, promotion service or registry activation. APPROVED_FOR_SANDBOX_TEST is a narrow review status; source_executed=false remains explicit. No generated source executes in this slice. The test-plan files and image reference are inert review artifacts; an execution consumer must independently qualify its runner and recheck authorization at dispatch/result publication.

Reviewer DB roles are trusted development control-plane principals with scoped table/column permissions, not OIDC identities or a tenant-isolated DB API. Raw DB access is not a customer-facing authorization interface. Database owners/superusers can change policy/triggers; this ledger is not administrator-proof or cryptographically signed. Provisioning and mapping actual independent reviewers is an operator action, never performed by the agent during ordinary execution. Automated tests use synthetic NOLOGIN roles in disposable schemas; they do not count as human approval.

## Migration and rollback

0003 is additive and preserves runtime/workspace rows. Stop API/worker/supervisor and back up before `alembic upgrade head` using the migration owner; the normal runtime remains non-owner. No existing workspace gains request_review permission. Existing digest-pinned workspace tasks will refuse the changed data-tool contract and need an explicit new task rather than silent repinning.

Normal rollback: stop the new code, preserve the review tables/evidence and restore a compatible application version; cancel/reconcile approval waits explicitly. Destructive downgrade to 0002 removes all review evidence and must require an approved backup/maintenance plan. Never drop the reviewer ledger in a production incident merely to force tasks to resume. Disposable-schema downgrade/re-upgrade is covered by tests.
