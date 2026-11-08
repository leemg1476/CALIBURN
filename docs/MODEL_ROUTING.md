# Hybrid model routing policy

## Goals

Support local and commercial inference while protecting customer data and keeping workflows reproducible. This does not mean that a task may automatically switch providers after failure.

## Routing decisions

Each task specifies a policy resolving:

1. Data classification and allowed residency: public, internal, confidential or regulated.
2. Model capability: function calling, context window, code performance, vision, structured output.
3. Availability/SLO and allowed provider-specific features.
4. Explicit budget and token/latency ceilings.
5. Egress authorization: on-prem-only by default for classified tenants; commercial route only when permitted.
6. Prompt/context redaction and retrieval privilege checks.

### Suggested baseline policies

- `LOCAL_ONLY`: All model traffic stays inside approved customer network; on local failure, stop and report. **No automatic commercial fallback**.
- `HYBRID_CONSENTED`: A designated tenant administrator preapproves data classes and providers; tasks that meet policy may route or fallback to approved endpoints.
- `COMMERCIAL_ALLOWED`: Public/non-sensitive tasks can use approved vendors with proper DPA and retention controls.

## Current bootstrap limitation

`CALIBURN_PROVIDER` chooses **one upstream** (fixture or OpenAI-compatible). `CALIBURN_ALLOW_COMMERCIAL_FALLBACK` is reserved as a future policy switch and currently triggers **no routing behavior**. This is intentional; implementing arbitrary fallback before tenant classification and audit would be unsafe.

## Capability scoring — later

Use task benchmark results instead of model name prestige. Track actual code/test pass rate, stable tool-call formatting, cost, p95 latency, context needs and retry behavior. Version prompts/model params for replayability and compare quality longitudinally.
