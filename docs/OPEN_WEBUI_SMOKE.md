# Open WebUI local smoke — reproducible development profile

This checks the actual unmodified Open WebUI interface against the CALIBURN durable runtime. It uses offline fixture inference and synthetic math prompts. No production identity, live inference, generated-code execution, external write or customer distribution clearance is established.

## Upstream artifact and license boundary

Tested Open WebUI **v0.13.0**, upstream commit `c38885a1a737da4968f157092f304f3b5481d0bf`, image:

`openwebui/open-webui@sha256:283efb20756785229a388bcd1e56a052f5284ae8c861717eed5eaaa3bba6b20a`

The image is the upstream Docker Hub mirror, pinned after pulling `openwebui/open-webui:0.13.0-slim`. GHCR returned registry denied on this host; no credentials were requested or bypassed. Version/commit were verified from the running image's startup output. No upstream UI source or branding was edited/copied into this repository. Its original name/logo/footer remain unchanged.

Read [the exact release LICENSE](https://raw.githubusercontent.com/open-webui/open-webui/v0.13.0/LICENSE) and [official license guidance](https://docs.openwebui.com/license/) before any distribution/branding decision. Local smoke is not legal clearance for customer resale/white-labeling. The [official quick-start](https://docs.openwebui.com/getting-started/quick-start/) documents the slim/version/mirror variants; [environment reference](https://docs.openwebui.com/reference/env-configuration/) documents the development/offline and execution switches used by this profile. No upstream license terms were silently changed.

## Start an isolated local fixture deployment

Use a new project name/volume: WEBUI_AUTH=false is only suitable for this loopback-only fixture test, never customer data. Do not apply the profile to an existing personal/company WebUI instance.

```powershell
$env:CALIBURN_API_TOKEN = [guid]::NewGuid().ToString('N')
$env:CALIBURN_DB_PASSWORD = [guid]::NewGuid().ToString('N')
$env:CALIBURN_DB_ADMIN_PASSWORD = [guid]::NewGuid().ToString('N')
$env:CALIBURN_WEBUI_SESSION_SECRET = [guid]::NewGuid().ToString('N')
$env:CALIBURN_PROVIDER = 'fixture'
$env:CALIBURN_UPSTREAM_API_KEY = ''
docker compose -p caliburn-webui-verify -f compose.yaml -f compose.webui-smoke.yaml --profile webui-smoke up --build --detach
```

The overlay disables code execution/interpreter, direct tool/terminal integrations and outbound model services; no generated tool is installed. UI has only the development API service token, no DB administrator credentials. API/worker remain non-root and on the internal network. PostgreSQL owner/migration credentials are separate from the runtime role. Session/API/DB values are generated in the operator environment and never placed in prompts, source, evidence JSON or screenshots. Keep any credentials you intend to retain in an approved secret manager; restarting with new random passwords does not rotate an existing DB volume.

Check WebUI health and actual Docker port mappings. On this Windows/Docker Desktop host, internal bridge bindings were not published despite HostConfig requests. Do not solve that by opening agent egress or mounting the Docker socket. A development-only workaround is:

```powershell
.venv/Scripts/python.exe scripts/webui_loopback.py --project caliburn-webui-verify
```

The loopback bridge is an operator host process using existing Docker CLI permissions to fixed WebUI/API container ports; it does not accept a target URL or execute model/source text. It logs no HTTP bodies, handles bidirectional bytes (including WebSockets/SSE), limits individual connections and must be stopped after testing. It is not production ingress or an installed background service. On hosts with normal published-port behavior it is unnecessary. Customer ingress/auth/egress design remains a release gate.

Open `http://127.0.0.1:8088`, dismiss the non-binding What's New panel, keep `caliburn-agent-durable` selected, and send `CALIBURN WebUI smoke: sum 17 25`. Verify the displayed result includes `"sum": 42.0`. No password/account/permission change is needed for this fresh fixture-only instance.

## Verified evidence

- `docs/evidence/m1-openwebui.png`: actual browser result with original upstream UI surrounding context.
- `docs/evidence/m1-openwebui.json`: pinned artifact, mocked-inference label, matching PostgreSQL task ID, COMPLETED, model calls=2, tool calls=1, result 42 and contiguous events 1..9. No token values recorded.
- `docs/evidence/m1-chat-disconnect.json`: separate real socket test disconnects after role/task-reference frame, observes QUEUED, starts a worker, observes COMPLETED and replays events 2..9.

The durable chat adapter supports normal JSON and OpenAI-compatible SSE framing. It emits the final completed answer, not live upstream token increments. Early disconnect stops only the HTTP waiter; the durable task continues. Step/tool progress and reconnection use `/api/v1/tasks/{id}/events` with a bearer and Last-Event-ID. An Open WebUI product task timeline and enterprise principal/repository grants are still not implemented.

## Stop / rollback

Stop only this named verification project's WebUI, worker, API and database containers. Stop the recorded loopback host process/session. Preserve the named DB/UI volumes for evidence; do not delete customer volumes. No database schema was added by the chat adapter or lifecycle fix; this profile creates its own new development database and runs the existing migrations. Rollback restores the previous adapter/application, but also restores its streaming 501 limitation; sandbox cleanup rollback restores a known cancellation defect, so retain reaping capability.

The screenshot proves a fixture answer round-trip, not broad Open WebUI feature compatibility, reliable autonomous coding, production isolation or legal clearance.
