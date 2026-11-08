# ADR 0013 — Independent evidence signatures with denial-only admission

Status: implemented and tested development slice; production activation intentionally remains unbuilt.

## Decision

Use pyca cryptography Ed25519 for actual independently verifiable signatures over a versioned domain-separated canonical evidence statement. Bind complete source/manifest/test/dependency declarations, current static and independently reviewed sandbox execution evidence, runtime checkpoint, scope, public key and validity window. Signatures attest integrity and signer identity under an independently trusted key; they do not upgrade incomplete qualification to production approval.

Add owner-only role/public-key trust mappings and immutable EVIDENCE_ONLY artifacts in migration0008. Distinct signer DB/process/key authority must not be inherited from runtime, source author, static verifier, execution reviewer or executor. Private material stays in an operator-owned encrypted file opened only by the signer; API/runtime/model/sandbox never receive it. Existing authenticated inspection and capability lookup are real read consumers that verify cryptography plus live revocation/source graph before returning evidence. Activation and invocation always deny.

Offline verification takes a separately trusted public key without a DB connection; it reports the same denial-only admission and cannot establish live revocation or release qualification. Online verification retains those live checks. SQL provenance/ACL triggers do not substitute for signature verification. Python JSON serialization is a project-specific format, not a general interoperable canonical JSON claim.

## Consequences and evidence

A passing stdlib test can now produce durable verifiable evidence without accidentally enabling arbitrary generated code. Wrong key, tampering, expiry, revoked roles/keys/review, self-signing, TEMP-map restoration and scope mismatch are tested. Separate real signer process, PostgreSQL ACLs, Docker execution and public read/unrelated-task consumers are exercised. Test inference remains scripted for Factory qualification; the separately recorded live LLM arithmetic smoke is not Factory quality evidence.

cryptography50.0.2 (Apache-2.0 OR BSD-3-Clause), cffi2.1.1 (MIT-0), pycparser3.12 (BSD-3-Clause) are recorded development dependencies. Binary/transitive OpenSSL notices and complete customer SBOM/legal review remain release gates; see LICENSING_AND_IP.md. No Open WebUI code, license or branding assumption changed.

Full security/license qualification, malicious test/subject anti-tamper, production signer custody, independent release approval, active registry, staged rollout/rollback and measured pinned execution reuse remain incomplete. See SIGNED_EVIDENCE.md for migration/rollback and exact control-plane actions. No production key/grant/activation was provisioned.
