"""Ed25519 evidence envelopes. A valid signature never grants execution authority."""

import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import Field, JsonValue, model_validator

from caliburn.sandbox.contracts import Bundle
from caliburn.tool_factory.contracts import CapabilityBundle, Contract, StaticReport, digest
from caliburn.tool_factory.execution_contracts import SHA, UUID, ExecutionResult

MAX_ENVELOPE_BYTES = 2_097_152
DOMAIN = b"CALIBURN\x00EVIDENCE_ONLY\x00ED25519\x00V1\x00"


class ArtifactDenied(Exception):
    pass


class EvidenceStatement(Contract):
    schema_version: str = Field(pattern=r"^caliburn-evidence-v1$")
    purpose: str = Field(pattern=r"^EVIDENCE_ONLY$")
    actor: str = Field(min_length=1, max_length=100)
    tenant: str = Field(min_length=1, max_length=100)
    key_id: str = Field(pattern=SHA)
    signer_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    artifact_policy_sha256: str = Field(pattern=SHA)
    issued_at: int = Field(ge=0)
    expires_at: int = Field(ge=1)
    bundle_ref: str = Field(pattern=UUID)
    bundle_sha256: str = Field(pattern=SHA)
    bundle: CapabilityBundle
    static_report_ref: str = Field(pattern=UUID)
    static_report_sha256: str = Field(pattern=SHA)
    static_report: StaticReport
    execution_job_ref: str = Field(pattern=UUID)
    execution_binding_sha256: str = Field(pattern=SHA)
    execution_binding: dict[str, JsonValue]
    execution_result_sha256: str = Field(pattern=SHA)
    execution_result: ExecutionResult
    decision: dict[str, JsonValue]
    plan_files: dict[str, str]
    production_approved: bool = False

    @model_validator(mode="after")
    def evidence_consistency(self):
        if self.production_approved or self.expires_at <= self.issued_at:
            raise ValueError("Evidence is not production authorization")
        bundle = self.bundle.model_dump()
        report = self.static_report.model_dump()
        result = self.execution_result.model_dump()
        run = self.execution_result.data
        binding = self.execution_binding
        if (
            digest(bundle) != self.bundle_sha256
            or digest(report) != self.static_report_sha256
            or digest(result) != self.execution_result_sha256
            or digest(binding) != self.execution_binding_sha256
            or not self.execution_result.ok
            or run is None
            or run.run.status != "PASSED"
            or report["classification"] != "REVIEW_REQUIRED"
        ):
            raise ValueError("Evidence hashes/outcome mismatch")
        if (
            self.static_report.bundle_sha256 != self.bundle_sha256
            or run.binding_sha256 != self.execution_binding_sha256
            or run.image_digest != binding.get("image_digest")
            or run.request_ref != self.decision.get("request_id")
            or self.decision.get("decision") != "APPROVE"
            or self.decision.get("binding_sha256") != self.execution_binding_sha256
        ):
            raise ValueError("Evidence authorization mismatch")
        if (
            binding.get("scope") != "factory_sandbox_test_only"
            or binding.get("actor") != self.actor
            or binding.get("tenant") != self.tenant
            or binding.get("bundle_ref") != self.bundle_ref
            or binding.get("bundle_sha256") != self.bundle_sha256
            or binding.get("report_ref") != self.static_report_ref
            or binding.get("report_sha256") != self.static_report_sha256
            or binding.get("source_sha256") != Bundle(files=self.bundle.sources).digest()
            or run.run.source_sha256 != binding.get("source_sha256")
            or run.run.plan_sha256 != binding.get("plan_sha256")
            or Bundle(files=self.plan_files).digest() != run.run.plan_sha256
        ):
            raise ValueError("Evidence artifact/scope mismatch")
        if len(self.model_dump_json().encode()) > MAX_ENVELOPE_BYTES - 1024:
            raise ValueError("Evidence envelope too large")
        return self


class SignedEvidence(Contract):
    algorithm: str = Field(pattern=r"^Ed25519$")
    statement: EvidenceStatement
    statement_sha256: str = Field(pattern=SHA)
    signature_hex: str = Field(pattern=r"^[0-9a-f]{128}$")


def canonical(statement):
    return json.dumps(
        statement.model_dump(),
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode()


def key_id(public_bytes):
    Ed25519PublicKey.from_public_bytes(public_bytes)
    return hashlib.sha256(public_bytes).hexdigest()


def sign(statement, private_key):
    if (
        not isinstance(private_key, Ed25519PrivateKey)
        or key_id(private_key.public_key().public_bytes_raw()) != statement.key_id
    ):
        raise ArtifactDenied()
    payload = canonical(statement)
    return SignedEvidence(
        algorithm="Ed25519",
        statement=statement,
        statement_sha256=hashlib.sha256(payload).hexdigest(),
        signature_hex=private_key.sign(DOMAIN + payload).hex(),
    )


def verify(envelope, public_bytes, *, actor, tenant, now):
    try:
        value = SignedEvidence.model_validate(envelope)
        statement = value.statement
        payload = canonical(statement)
        if (
            statement.actor != actor
            or statement.tenant != tenant
            or not statement.issued_at <= now < statement.expires_at
            or statement.key_id != key_id(public_bytes)
            or value.statement_sha256 != hashlib.sha256(payload).hexdigest()
        ):
            raise ArtifactDenied()
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            bytes.fromhex(value.signature_hex), DOMAIN + payload
        )
        return value
    except (ValueError, TypeError, InvalidSignature, RecursionError) as exc:
        raise ArtifactDenied() from exc


def parse(raw):
    if not isinstance(raw, bytes) or len(raw) > MAX_ENVELOPE_BYTES:
        raise ArtifactDenied()

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON key")
            result[key] = value
        return result

    def constant(_):
        raise ValueError("Nonfinite JSON")

    try:
        return SignedEvidence.model_validate(
            json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise ArtifactDenied() from exc


def admission(envelope):
    # This schema seals incomplete evidence, not a qualified release or executable grant.
    return {
        "signature_valid": True,
        "can_invoke": False,
        "activation_eligible": False,
        "blockers": [
            "security_incomplete",
            "license_unreviewed",
            "release_approval_missing",
            "active_registry_not_built",
        ],
        "scope": envelope.statement.purpose,
    }
