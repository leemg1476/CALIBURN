# Credential broker design

## Problem

An autonomous agent may need to inspect repos, invoke customer APIs, search enterprise data or operate cloud services. Embedding permanent account passwords or admin/master API keys in prompts, MCP configurations and generated code destroys tenant isolation and makes incident response nearly impossible.

## Credential broker model

`User OIDC/SSO → Delegated Grant → Vault/KMS Reference → Policy Decision → Short-lived Tool Handle → Tool Runner → Target Service`.

### Objects

- `Principal`: tenant, verified person/service ID, role and identity assurance level.
- `Connection`: target system, permitted OAuth/KMS integration, owner, allowed resources.
- `Grant`: principal/task/tool digest/scopes/resources/TTL and approval receipt.
- `Handle`: opaque, short-lived reference with one-time or bounded use, never raw secret.
- `Lease`: ephemeral credentials resolved inside trusted runner and revoked on task end where supported.
- `AuditReceipt`: policy version, decision, access time, target action, sanitized outcome.

### Example

1. User requests "inspect team/repo CI history".
2. Gateway validates tenant, OIDC user and repo membership; requests `gitlab.read_pipeline` grant scoped to `team/repo` for 10 minutes.
3. Agent sees tool schema and opaque `grant_id`, **not** OAuth refresh/access token.
4. Runtime verifies `task_id`, tool signed digest, expiry, operation, target repo and risk.
5. Broker obtains delegated access from secret store and injects short-lived material into the trusted tool runner through a controlled secret channel.
6. Runner calls GitLab, redacts response/logs, destroys lease material and records a receipt.
7. Revocation instantly blocks *new* calls; long-running external operations need separate reconciliation.

## Special considerations

- OAuth `authorization_code + PKCE` for user grants; `client_credentials` for service actors where appropriate. Avoid saving users' passwords.
- OAuth scope may not enforce repository/project-level limits; **application authorization must still check resource boundaries**.
- Use OpenBao with per-tenant paths, token policies, audit logging, seal/unseal procedures and backup policies; review chosen plugins and HA mode.
- Expose secret metadata in UI (service, scope, expiry, consent), never token values.
- Separate service admin, security review and user self-service approval permissions.
- Deny fallback from user-scoped delegated token to master token if a call fails.
- For on-prem customer installations, route outbound API access via customer-approved egress proxies.

## Required tests

Wrong tenant, wrong repo, wrong tool digest, expired token, revoked grant, tool attempt to print a credential, runner crash during lease and forced secret rotation.
