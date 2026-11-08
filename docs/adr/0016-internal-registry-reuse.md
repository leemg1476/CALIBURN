# ADR 0016: executable internal pure-JSON releases

Status: accepted for development/internal demonstration, 2026-11-08.

The evidence-only Factory could accumulate proofs but could not consume its own generated functionality. Add a separate executable internal release namespace without changing the meaning of historical EVIDENCE_ONLY signatures.

Schema0009 records requests, hash-bound decisions, signed immutable versions, active heads/history, invocations and revocations. A release binds current qualification, source, manifest, fixed image and policy implementation. PostgreSQL roles separate runtime writes, approval records, signing and executor receipts. The user explicitly delegates development/internal-demo decisions to the trusted development agent, including its own proposals. This replaces the blanket prohibition on self-approval; the actual approving authority must still be recorded. Runtime/model-produced text has no approval privilege.

The first executable tier is one Python source file with a closed JSON ABI, no dependencies, imports, attributes or requested permissions, and bounded Docker execution. An inert AST/ABI profile narrows applicability; the container supplies execution isolation. Existing owner fixtures and host-owned repeat/order/replay observations are required. License clearance is explicitly internal only; a declared identifier is not customer redistribution clearance.

At task submission the server selects active releases under its configured actor/tenant and snapshots immutable versions. The Worker advertises typed functions and queues invocations; a separately mapped trusted executor starts the fixed non-root network-none image. Source never imports into the API/Worker. New head selection does not alter old task pins; revocation/expiry blocks both. Failed execution or invalid output quarantines the version. Recovery uses bounded attempts, leases and stale-nonce fencing; pure computation may rerun after a crash, so this is not exactly-once execution.

The read API exposes catalog and per-version counts. Activation remains control-plane only. The existing development service identity is not tenant SSO. Production signing custody, broader SAST/dependency/license assurance, external effects, MCP/Skills and enterprise authorization remain separate milestones.

Rollback: disable CALIBURN_ALLOW_REGISTRY_INVOCATION for new tasks, cancel/drain in-flight invocations, revoke affected releases or move the active head to an unrevoked approved version. Preserve source, evidence and images. Before database downgrade0008 export registry data; downgrade drops the nine new tables and their trigger functions, so it is destructive and requires explicit authorization. Ordinary rollback does not need a database downgrade.
