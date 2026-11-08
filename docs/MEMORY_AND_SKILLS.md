# Durable memory and reusable skills

## Why raw chat history is insufficient

Raw transcripts mix facts, hypotheses, temporary failures, secrets, irrelevant noise and contradictory instructions. Merely putting them into a vector index does not produce dependable organizational memory.

## Memory processing pipeline

`RAW TRACE → CANDIDATE → CLASSIFY → NORMALIZE → DEDUP/CONFLICT → VERIFY → APPROVE → INDEX → RETRIEVE → EXPIRE/REVALIDATE`.

### Memory classes

| Class | Contents | Verification requirement |
| --- | --- | --- |
| Fact | Stable property of repo/service or externally sourced domain fact | Provenance, time, confidence, freshness |
| Decision | Accepted architectural/business choice | Decision maker, scope, supersession history |
| Lesson | Observed task failure and successful repair | Before/after logs, reproduction, applicability test |
| Skill | Parameterized procedure, references and tests | Test fixtures, allowed actions, version |
| Preference | Authorized user/tenant behavior preference | Verified owner, privacy scope, revocation |

### Promotion rules

- A model-extracted claim begins as `CANDIDATE`, not trusted memory.
- Deduplicate by normalized subject/predicate/scope/version; never collapse contradictory entries silently.
- Verify against test output, source-of-truth files, reviewer judgment or repeated observations appropriate to memory class.
- Record applicable repo branch, runtime, dependency versions and environment constraints.
- Attach expiration/revalidation triggers; supersede old version rather than overwrite evidence.
- Exclude credentials, unnecessary personal data and opaque user content from globally visible memory.

### Retrieval rules

Use filters **before** embedding similarity: tenant, actor permissions, task context, repo, artifact version, language, policy, validated status and freshness. Retrieval yields suggestions with evidence references, not model system instructions. Log which memory item influenced an action and whether its advice succeeded.

### Skill vs Tool vs MCP

- **Skill:** repeatable procedure or operating manual, mostly declarative, with applicability and tests.
- **Tool:** typed callable capability executed by a trusted/sandboxed runner.
- **MCP server:** transport/application exposing one or more tools/resources and subject to gateway permission/contract checks.
- **Memory:** accumulated verified context/knowledge; may recommend Skill/Tool selection but does not itself grant execution rights.

## Quality metrics

Retrieval precision, applicability precision, contradiction rate, stale-memory use rate, task-success uplift, token reduction, cross-tenant leakage count and regression rates after policy/model upgrades.
