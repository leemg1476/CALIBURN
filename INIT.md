# CALIBURN — Project initialization brief

## Vision

Build a **commercializable, model-agnostic enterprise autonomous agent platform**, starting from a web-chat interface, with Codex-class coding autonomy and a general-purpose work runtime. The critical differentiator is **capability compounding**: the system can propose, implement, test, govern, publish, and safely reuse its own Tools/MCPs and Skills over many runs.

## Non-negotiable requirements

1. **Web UI:** Open WebUI integration first; keep UI replaceable behind a protocol boundary. Never assume the Open WebUI license grants white-label rights.
2. **Model independence:** Local vLLM/Ollama-compatible and commercial OpenAI-compatible APIs, configurable per tenant/task/classification, with no silent cross-boundary data transfer.
3. **Autonomy:** Multi-step inspect → plan → execute → validate → repair → summarize loop; explicit bounded budgets, cancel, resume, durable state and artifacts.
4. **Tool factory:** Autonomous *proposal* of code, manifests and tests; isolated evaluation; static/security scans; replay/regression; human/policy approval; immutable signed version; registry publication; rollback and usage feedback.
5. **Skills + memory:** Curated durable procedural memory and tested skills, each with provenance, applicability, confidence and expiry; no raw chat-log injection as policy.
6. **Credential broker:** User/tenant/service identity, OAuth/OIDC delegation, vault-managed credentials, short-lived scoped handles, tool-specific secret injection outside the model prompt, rotation and revocation.
7. **Enterprise operations:** OIDC SSO, RBAC/ABAC, tenant isolation, usage quotas, approval gates, trace/audit records, SBOM, deployable on-prem/air-gapped where dependencies permit.
8. **Commercial delivery:** Dependency/license review, clean third-party boundaries, exportable configuration, deterministic deployment and supportable upgrades.

## Not the goal

- Training an LLM from scratch.
- A graph full of single-purpose manually scripted agents.
- Generating tools and immediately executing them in the privileged API process.
- Giving a model permanent passwords, unrestricted host shells, unbounded budget or broad network access.
- Representing a green unit test as a guarantee of production safety.

## First working demonstration

**Scenario A — Code task:** User submits a repo issue → isolated workspace → code change → unit/integration tests → diff and evidence → user approval → optional PR. Resume after worker restart.

**Scenario B — Self-created reusable capability:** A task requires a connector not yet registered → agent drafts MCP/Tool + contract + tests → sandbox tests and policy checks → human approval → immutable registry version → another task invokes it with observable success/failure.

**Scenario C — Credentialed external task:** User grants a limited OAuth scope → broker issues a tool-bound short-lived capability → tool accesses an allowed API → logs are redacted → revocation blocks further use and never exposes secret material to the LLM.

## Definition of done

Do not call the system 'Codex-class' until longitudinal tests demonstrate reliable completion on real repositories, including retries, resumability, invalid dependencies, injection attacks, safe tool promotion, and enterprise auth workflows. A demo does not imply operational assurance.

## Handoff

Start with `docs/IMPLEMENTATION_PLAN.md`. Implement its M1 vertical slice and do not skip foundational state, security and audit contracts just to display chat output sooner.
