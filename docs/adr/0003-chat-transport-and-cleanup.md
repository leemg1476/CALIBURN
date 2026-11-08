# ADR 0003 — Durable chat transport and owned sandbox cleanup

Status: implemented development corrections; no new candidate execution or production approval.

## Verified issue and correction

After prior M2 checks, authoritative Docker inventory showed a legacy `caliburn-sbx-*` container in Created state (not running, PID 0, no host mounts/network). The earlier point-in-time no-container observation did not prove that a pending Docker daemon create could not complete later. The test-only legacy instance was removed by exact name after inspection; unlabeled/legacy instances are never swept by a broad wildcard.

The create handshake previously shielded communicate() only after create_subprocess_exec returned a process handle. Cancellation before handle assignment could leave the CLI/daemon create unowned. The entire spawn-and-create coroutine is now shielded and retained. If its caller times out/cancels, it joins the bounded creation operation and both immediate/late completion own removal of that generated name. A deterministic real-process regression delays a Docker create request while cancellation lands before handle return, then confirms no late container remains.

Every new managed-v2 container carries an expiry label at creation (before start). The existing trusted supervisor reaps expired instances at startup and at five-second idle/iteration intervals. Only matching ownership marker, generated name, finite expired timestamp, internal network/no-host-data configuration qualify. Future, malformed, differently named, legacy and host-data instances are preserved. A reaper-only CLI uses existing operator Docker rights; no agent socket/privilege is added. A stopped supervisor does not schedule itself: restart or explicit operator reaping is required for Created instances after process death. Running data runners retain their independent 25-second alarm. Extended Docker daemon outage/host restart qualification remains a production gate.

No database schema migration. Rollback can restore the previous code but reintroduces the cancellation defect; preserve the managed-v2 cleanup operator before doing so. Neither recovery path executes source or deletes host files/volumes.

## Open WebUI compatibility

A real pinned unmodified Open WebUI v0.13.0 slim instance is used only for local development validation. Its default chat workflow needed OpenAI-compatible streaming responses, while the M0 gateway explicitly returned 501 for all streaming requests. Durable chat adaptation is now isolated in chat_adapter.py: persist task, emit role/task-reference frame, await the independent durable worker, emit the completed result/final stop/[DONE]. Failure after headers uses a bounded error frame. This is completion-level compatibility, not token-by-token upstream inference. M0 direct chat remains nonstreaming; task SSE remains the distinct authorized monotonic/reconnectable progress protocol.

Actual socket tests close after the initial chat frame while no worker exists, verify QUEUED persisted work, start a separate worker, verify COMPLETED and replay task events. Browser smoke verifies the original UI displays the fixture math result 42, backed by the matching PostgreSQL task and event record. Inference is mocked; UI, transport, DB and worker are real. Product task timeline, enterprise identity and live model quality remain separate open requirements.

## Local transport and deployment boundary

The target Docker Desktop did not expose ports on the internal-only bridge (HostConfig contained bindings, NetworkSettings showed empty exposed port lists). Agent containers stay on the existing internal network. For this development test only, a bounded fixed-target loopback byte transport uses an operator's existing Docker exec access to the WebUI/API services. It supports HTTP/SSE/WebSocket bytes without body logging, runs outside agents and is not installed as a service. It must not be exposed beyond loopback or treated as production ingress. A customer deployment needs its own approved authenticated ingress/network design.

The optional smoke Compose overlay pins the exact UI image digest, keeps original branding, uses a fresh isolated data volume, disables WebUI code execution/interpreter/direct integrations and external inference, and binds only local development ports. It uses auth-disabled fresh-install mode solely for fixture data, not enterprise authentication. No upstream source, trademark, license or branding is altered. The exact release LICENSE was read; this smoke is not distribution/white-label/SBOM/legal clearance.
