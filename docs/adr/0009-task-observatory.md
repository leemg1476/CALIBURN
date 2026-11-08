# ADR 0009 — Authenticated task timeline and controls

Status: implemented and verified in an actual browser with PostgreSQL and a separate worker; development identity only.

## Decision

Serve a small independent console at /tasks/ui and three explicitly allowlisted static assets from caliburn.web. It consumes the existing authenticated task/control/review/event APIs plus a new bounded history projection. No Open WebUI source, markup or branding is copied or changed; no new UI library, CDN/font dependency or customer license clearance is introduced.

GET /api/v1/tasks/{id}/history returns budget/deadline, paginated Run metadata and Step status/attempt/tool/input-output hashes. It excludes worker lease tokens and raw step model/tool inputs/outputs. Server-owned actor/tenant authorization precedes reads; known platform credentials in the projection fail closed. Step ordinal and run offset cursors have bounded limits. History reads do not acquire a worker lease or mutate task state.

The console shows current state/result, reserved budgets, real steps/runs, independent-review status and recent events. Pause/cancel/resume invoke existing server transitions; WAITING_APPROVAL cannot be resumed by the general client. There is no approval write action. A canceled task's pending request is displayed as undecided/ended rather than an actionable review wait.

Use same-origin fetch SSE with Authorization headers, since browser EventSource cannot supply this bearer contract. Decode split UTF8/CRLF frames with bounded buffering; enforce task/event identity and contiguous numeric sequences; deduplicate replay and advance the cursor only after rendering the accepted batch. Automatic transport retries use Last-Event-ID and bounded exponential backoff. Explicit disconnect/page hide aborts requests and drops the token; a new manual connection replays from zero. Keep at most 250 displayed events; history remains available in the server.

The token is entered by the operator and held only in the active JS session, never URLs/storage/cookies/source/traces/model input. No raw HTTP error body is displayed. All dynamic source/event/result strings use textContent; no innerHTML/eval/HTML interpretation. CSP uses self-hosted scripts/styles/connect only, no inline script, no framing/base navigation; assets are no-store and nosniff. Private data/control still requires bearer authorization even though the inert page is public.

## Evidence

Actual browser: QUEUED → PAUSED → API restart → automatic reconnect at visible cursor2 → resume → separate fixture worker → COMPLETED,3 Steps,1 Run,2 model calls/1 tool call,result42,11 unique events. Confirmed wrong-token denial, empty token field after connection, queued/review-wait cancellation, disabled resume during independent review, canceled pending-review label, literal HTML/script result with zero inserted img/script elements, and narrow viewport without horizontal overflow. Desktop/mobile/review/literal-result screenshots and PostgreSQL histories are saved in docs/evidence.

Node built-in tests cover split UTF8/CRLF/comments/multiline SSE, contiguous replay/duplicate/gap/identity/resource boundaries and control permissions. Python tests cover asset scope/CSP/auth/pagination/hashes/read-only behavior/known-credential denial on both DB dialects. Wheel packaging includes all four HTML/CSS/module assets. Fixture model/reviewer/source data is explicit; this is not real-model coding quality, enterprise tenant identity or a production security certification.

## Limits and rollback

Standalone console requires an existing Task ID and development service token. Open WebUI embedded task navigation, OIDC/individual authorization, production HTTPS/session design and operational scale qualification remain open. Reserved token/cost counters are not verified vendor billing. Automatic stream recovery retains the in-memory cursor; reload/new manual connect retrieves durable history again rather than persisting browser credentials/cursors.

No schema migration; current head0004 and existing runtime behavior stay unchanged. Rollback removes web routes/history projection/assets and restores previous application code; preserve all task/event/evidence data, no DB downgrade. Static files are explicitly packaged; wheel and source deployments both need them. Browser fixture processes are loopback-only and stopped after qualification; no persistent public service was installed. Git-image approval remains pending and is unrelated to this UI work.
