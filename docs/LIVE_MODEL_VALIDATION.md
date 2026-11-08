# Explicit paid-model development validation

The user authorized paid calls and capped cumulative requests at100 and input+output usage at50,000 tokens. This is a maximum, not a target. The supplied credential file is actually .env.apikey (the user called it .env.api). It is Git/Docker ignored. Never print it, commit it, copy it into an image or mount it into a sandbox. Normal fixture tests never load it.

CALIBURN_API_ENV_FILE explicitly reads a bounded nonexecuting UTF-8 key/value file. Supported aliases: openai_api_key / openai_model / openai_base_url and CALIBURN_UPSTREAM_API_KEY / MODEL / BASE_URL; explicit process environment wins. Unknown/duplicate/malformed entries fail with values redacted. Loading the file grants no network use or execution/approval permissions. Provider remains fixture unless explicitly configured openai_compatible. URL credentials/query/fragment are rejected and Settings repr omits bearer/upstream key/DSN.

Official OpenAI requests use Chat Completions max_completion_tokens, store=false, standard/default service tier, and gpt-6-luna reasoning_effort=none for documented Chat function-call support. Other compatible endpoints retain max_tokens. No automatic provider fallback or redirect is performed. Primary references: [model](https://developers.openai.com/api/docs/models/gpt-6-luna), [Chat create](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create). This is not the Responses API, full reasoning-agent validation or a provider-independent routing/residency policy.

## Actual smoke

```powershell
# Disposable PostgreSQL, migrated owned schema, no existing queued tasks:
$env:CALIBURN_DATABASE_URL='postgresql+psycopg://postgres@127.0.0.1:55432/caliburn_test?options=-csearch_path%3Dcaliburn_live_20261108'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe scripts/live_llm_smoke.py --allow-paid --api-env-file .env.apikey
```

Observed real gpt-6-luna → durable worker → add_numbers(19,23)=42 → add_numbers(42,5)=47 → final47. Task4b85498e-7170-427b-8c31-a1af16912e34 COMPLETED,3 model calls,2 tools,745 reported total tokens (699 input,46 output). No mocks for model/PG/tools in this smoke. Commercial fallback remained false. Sanitized evidence is docs/evidence/live-llm-smoke.json. This verifies two dependent tool calls and persisted completion, not repository coding quality, autonomous security or broad model accuracy.

The opt-in script reserves a conservative encoded-input+overhead+max-output allowance before each request and persists attempts/charged tokens in ignored .caliburn/live-llm-budget.json. Successful reported usage refunds unused reservation; unknown/failed/interrupted attempts retain it. No automatic retry/fallback in the adapter. The worker's own smaller step/tool/call/time limits also apply. The script caps each response at256 output tokens and this scenario at6 model/4 tool calls. Its0.01 call-cost reservation is a development allowance, not verified vendor billing or a price quotation. The full50,000/100 cap is shared across subsequent script runs through that file; preserve it to retain cumulative accounting. Use one smoke process at a time. This is a development ledger, not a tamper-resistant account-wide quota for unrelated clients.

Reproducing the smoke incurs additional paid usage and requires continuing explicit authorization plus a disposable migrated schema. Unit pytest transports remain mocked; they check exact request/credential separation and failure behavior without spending API credit. API keys remain outside messages/traces/evidence. M4 vault custody and enterprise principal/tenant mapping are still open.
