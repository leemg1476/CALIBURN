# First message to Codex CLI

You are the primary engineer building CALIBURN, an enterprise autonomous agent platform. This repository is a contract-first bootstrap, not a completed product.

Read `AGENTS.md`, `INIT.md`, and all `docs/*.md` before changing code. Start with milestone M1 in `docs/IMPLEMENTATION_PLAN.md`. First:

1. Inspect the existing working Python spike and execute all tests.
2. Report implemented-vs-target gaps against the acceptance tests, architecture, security and commercial license constraints.
3. Propose the smallest M1 vertical slice with a persistent task runner/worker, append-only events and resumability, including database schema and SSE/WebSocket transport decisions.
4. Implement it, including migrations, API contracts, abort/restart tests, explicit timeouts and no host-command privilege.
5. Provide a reproducible demo from WebUI → gateway → durable task → trace/evidence response.

Never implement arbitrary source execution in the API container. Never auto-promote generated Tool/MCP code. Do not remove or obscure Open WebUI branding. Keep the backend UI-independent. Every change must include negative tests and a summary of actual behaviors and missing functionality.

Continue iteratively through milestones with a short review before changes that alter auth trust boundaries, license position or external write permissions.
