# Commercial licensing and naming checklist (review before resale)

**Not legal advice.** Verify the exact commit/tag of every bundled dependency and have company legal counsel confirm redistribution, deployment, attribution, data protection and trademark clearance.

## The key Open WebUI issue

Open WebUI versions **v0.6.6 onward** carry a project-specific license including **branding restrictions**. The project's official documentation states that above the limited-user exemption you generally may not remove, alter, obscure or replace their name/logo, and their guidance forbids ordinary co-branding without the necessary permission. Enterprise/white-label rights require an appropriate license. Source:

- https://docs.openwebui.com/license/
- https://docs.openwebui.com/enterprise/
- https://github.com/open-webui/open-webui/blob/main/LICENSE

**Recommended commercial architecture:** Keep CALIBURN's proprietary autonomous backend separate and expose standard interfaces (OpenAI-compatible, task API, SSE/events) to a **replaceable UI adapter**. For early pilots, run unmodified-branded Open WebUI while complying with its license. Before packaging a customer-facing CALIBURN-branded UI: either negotiate Open WebUI enterprise/white-label terms or build/license an independent UI with terms permitting distribution and branding.

Open WebUI documentation reports the v0.6.5 codebase as available under earlier BSD-3 terms, but deliberately freezing an old UI has security/upstream maintenance costs and is not automatically the best enterprise path.

Do not copy Open WebUI source into this repo yet. Connect it as a standalone, separately reviewed component. Reconfirm current version and derivative-work obligations before copying source or modifying branding.

## Dependency register (provisional, no clearance claim)

| Component | Intent | Decision gate |
| --- | --- | --- |
| FastAPI / Pydantic / HTTPX | Bootstrap API | Verify exact transitive licenses with SBOM |
| Open WebUI | Replaceable external web chat | Current Open WebUI branding terms or separate commercial license |
| LangGraph (optional) | Agent execution/checkpointing alternative | Confirm version/benefit; avoid hard coupling until M1 choice |
| MCP SDK | Tool transport/contract | Verify actual package license, vendoring and dependency chain |
| PostgreSQL | Production task/event store | Confirm distributed binary obligations if bundled |
| OpenBao or Vault-compatible store | Credential broker | Review chosen distribution, plugin ecosystem and hosting model |
| Local models + vLLM | Local inference | Check **model weights'** licensing separately from inference-server source |
| Commercial models | Optional delegated inference | Data use, residency, retention, API terms, customer DPA |

## CALIBURN brand/name

The name is connected with the Arthurian sword tradition (often identified with Excalibur); that historical reference alone does **not** establish modern trademark availability. Existing organizations use similar names in technology sectors. Before marketing or signing B2B contracts:

- Search KIPRIS (Korea), USPTO and WIPO, including `CALIBURN`, `CALIBURN AI`, Korean transliteration and relevant software classes.
- Check domains, app/package registries, code repositories and confusingly similar enterprise AI brands.
- Obtain counsel's clearance for Korea and intended export markets; avoid implying association with King Arthur media franchises.
- Treat `CALIBURN` as a **working project name** until clearance.

Background on name: https://www.smithsonianmag.com/history/king-arthur-real-person-180980466/

## M1 dependency additions — provisional, not distribution clearance

The runtime adds SQLAlchemy, Alembic and psycopg/psycopg-binary as external dependencies, without vendoring their source. Observed development resolution: SQLAlchemy 2.1.8, Alembic 1.20.1, psycopg and psycopg-binary 3.3.8. PostgreSQL test/deployment uses the postgres:17-alpine image, and the backend uses python:3.12-slim. The current dependency ranges/image tags are not a reproducible customer lockfile or legal approval. Exact versions, transitive licenses, binary notices, image digests and SBOM must be reviewed and locked before redistribution. Existing ownership, Open WebUI branding and legal gates remain in force; no rights or clearance are inferred from successful installation/testing.

M2 read/patch data runner reuses the existing Python base-image family and standard library. It does not vendor or add Git to the distributed agent/sandbox image; local Git import is an explicit operator-host dependency. No dependency/branding/distribution clearance is inferred. Before shipping any sandbox image, lock its base/digest and include it in the existing SBOM/license/security review gate.

Proposed Git data image (not yet built/approved): deploy/sandbox/Dockerfile.git pins the existing Python base digest and proposed Debian Git 1:2.47.3-0+deb13u1 plus required dependencies. [Debian's package page](https://packages.debian.org/trixie/git) identifies that version and source/dependency/copyright links; [upstream COPYING](https://raw.githubusercontent.com/git/git/master/COPYING) identifies GPLv2. This adds a binary/dependency distribution surface and is an explicit approval gate under the user's instruction. No customer redistribution, proprietary-code licensing conclusion or legal clearance is inferred. Build defaults blocked; after development approval, retain dpkg inventory/copyright, inspect exact transitive versions and continue source/notice/SBOM/security/customer review before distribution. See GIT_DATA_APPROVAL.md and ADR0008. Existing stdlib-only images and operator-host Git remain separate.

## Open WebUI validation artifact — development only

Actual unmodified Open WebUI v0.13.0 slim browser smoke was performed with the official documented Docker Hub mirror, pinned image digest and source commit recorded in OPEN_WEBUI_SMOKE.md. The exact tagged [LICENSE](https://raw.githubusercontent.com/open-webui/open-webui/v0.13.0/LICENSE) and [official branding guidance](https://docs.openwebui.com/license/) were read. No upstream source was copied into this repository or branding altered. The optional profile is a local fixture test, not customer distribution, endorsement, white-label rights, legal clearance or a replacement for the exact-image SBOM/customer release review.


## Approved Git development build and signing dependency resolution (2026-11-08)

The previously proposed exact Git development build/local fixture validation was explicitly approved and succeeded without version changes. This supersedes the earlier pending-build status only. See GIT_DATA_APPROVAL.md and docs/evidence/git-dev-image-inventory.json for image digest,118 package/version entries and retained Git copyright. No customer redistribution/source-provision/legal clearance follows from development approval.

Backend/signer now depends on cryptography==50.0.2, observed Apache-2.0 OR BSD-3-Clause; installed Windows transitive cffi2.1.1 MIT-0 and pycparser3.12 BSD-3-Clause. Version/license-file hashes are recorded in docs/evidence/signing-dependency-inventory.json. No source vendoring or Open WebUI branding/license change occurred. Primary sources: [exact cryptography release](https://pypi.org/project/cryptography/50.0.2/), [exact license](https://raw.githubusercontent.com/pyca/cryptography/50.0.2/LICENSE), [binary installation guidance](https://cryptography.io/en/50.0.0/installation/). Windows cryptography wheels bundle OpenSSL; exact binary/transitive notices, reproducible customer dependency/image lock and complete SBOM/security/legal review remain mandatory release work. The inventory is development evidence, not a complete SBOM or customer clearance.
