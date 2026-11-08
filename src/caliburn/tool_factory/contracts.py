"""Bounded proposal metadata and deterministic JSON contract/fixture validation."""

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, field_validator, model_validator

from caliburn.sandbox.contracts import Bundle, safe_path


def digest(value):
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def finite(value):
    return (type(value) is int and value.bit_length() <= 1024) or (
        type(value) is float and math.isfinite(value)
    )


def supported_schema(schema):
    count = 0

    def visit(node, depth):
        nonlocal count
        count += 1
        allowed = {
            "type",
            "properties",
            "required",
            "additionalProperties",
            "items",
            "description",
            "minimum",
            "maximum",
            "minLength",
            "maxLength",
            "minItems",
            "maxItems",
        }
        if not isinstance(node, dict) or depth > 6 or count > 128 or set(node) - allowed:
            raise ValueError("Unsupported contract schema")
        kind = node.get("type")
        if kind not in {"object", "array", "string", "integer", "number", "boolean", "null"}:
            raise ValueError("Explicit contract type required")
        if "description" in node and (
            not isinstance(node["description"], str) or len(node["description"]) > 500
        ):
            raise ValueError("Invalid schema description")
        if kind == "object":
            properties, required = node.get("properties"), node.get("required", [])
            if (
                not isinstance(properties, dict)
                or len(properties) > 32
                or node.get("additionalProperties") is not False
                or not isinstance(required, list)
                or any(not isinstance(key, str) for key in required)
                or len(set(required)) != len(required)
                or set(required) - properties.keys()
            ):
                raise ValueError("Closed object contract required")
            for key, child in properties.items():
                if not re.fullmatch("[a-zA-Z_][a-zA-Z0-9_]{0,63}", key):
                    raise ValueError("Invalid contract property")
                visit(child, depth + 1)
        elif any(key in node for key in ("properties", "required", "additionalProperties")):
            raise ValueError("Object fields on nonobject contract")
        if kind == "array":
            visit(node.get("items"), depth + 1)
        elif "items" in node:
            raise ValueError("Array fields on nonarray contract")
        for lo, hi, kinds in (
            ("minimum", "maximum", {"integer", "number"}),
            ("minLength", "maxLength", {"string"}),
            ("minItems", "maxItems", {"array"}),
        ):
            for key in (lo, hi):
                if key in node and (
                    kind not in kinds
                    or type(node[key]) not in (int, float)
                    or not finite(node[key])
                    or (
                        key not in {"minimum", "maximum"}
                        and (type(node[key]) is not int or not 0 <= node[key] <= 4096)
                    )
                ):
                    raise ValueError("Invalid schema bound")
            if lo in node and hi in node and node[lo] > node[hi]:
                raise ValueError("Inverted schema bound")

    visit(schema, 0)
    if schema.get("type") != "object":
        raise ValueError("Top-level object contract required")
    return schema


def matches(schema, value):
    kind = schema["type"]
    if kind == "object":
        return (
            isinstance(value, dict)
            and not (set(value) - schema["properties"].keys())
            and set(schema.get("required", [])) <= value.keys()
            and all(matches(schema["properties"][key], item) for key, item in value.items())
        )
    if kind == "array":
        return (
            isinstance(value, list)
            and schema.get("minItems", 0) <= len(value) <= schema.get("maxItems", 4096)
            and all(matches(schema["items"], item) for item in value)
        )
    if kind == "string":
        return isinstance(value, str) and schema.get("minLength", 0) <= len(value) <= schema.get(
            "maxLength", 100000
        )
    if kind in {"integer", "number"}:
        valid = type(value) is int if kind == "integer" else type(value) in (int, float)
        return (
            valid
            and finite(value)
            and schema.get("minimum", -math.inf) <= value <= schema.get("maximum", math.inf)
        )
    return type(value) is bool if kind == "boolean" else value is None


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)


class PermissionRequest(Contract):
    action: Literal["read_data", "write_data", "network_read", "network_write"]
    resource: str = Field(min_length=1, max_length=200)
    grant_ref: str | None = Field(default=None, pattern=r"^grant:[a-z0-9-]{1,80}$")


class Dependency(Contract):
    name: str = Field(pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$")
    version: str = Field(pattern=r"^[0-9][a-zA-Z0-9_.+-]{0,49}$")
    declared_license: str = Field(min_length=1, max_length=100)


class Manifest(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    version: str = Field(
        pattern=r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$", max_length=30
    )
    kind: Literal["tool", "mcp", "skill"]
    description: str = Field(min_length=1, max_length=1000)
    entrypoint: str = Field(min_length=1, max_length=250)
    input_schema: dict[str, JsonValue]
    output_schema: dict[str, JsonValue]
    permissions: list[PermissionRequest] = Field(default_factory=list, max_length=16)
    timeout_seconds: int = Field(default=10, ge=1, le=60)
    failure_modes: list[str] = Field(min_length=1, max_length=16)
    _schemas = field_validator("input_schema", "output_schema")(supported_schema)


class Fixture(Contract):
    name: str = Field(min_length=1, max_length=80)
    input: dict[str, JsonValue]
    expected: dict[str, JsonValue]


class CapabilityBundle(Contract):
    manifest: Manifest
    sources: dict[str, str]
    tests: dict[str, str]
    fixtures: list[Fixture] = Field(min_length=1, max_length=16)
    dependency_lock: list[Dependency] = Field(default_factory=list, max_length=32)
    sbom_components: list[Dependency] = Field(default_factory=list, max_length=32)
    declared_license: str = Field(default="LicenseRef-Unreviewed", max_length=100)

    @model_validator(mode="after")
    def validate_bundle(self):
        Bundle(files=self.sources)
        Bundle(files=self.tests)
        if self.sources.keys() & self.tests.keys():
            raise ValueError("Source and test paths must be distinct")
        path, _, symbol = self.manifest.entrypoint.partition(":")
        safe_path(path)
        if path not in self.sources or (
            self.manifest.kind != "skill"
            and (not path.endswith(".py") or not re.fullmatch("[a-zA-Z_][a-zA-Z0-9_]*", symbol))
        ):
            raise ValueError("Declared source entrypoint required")
        if self.manifest.kind == "skill" and (symbol or not path.endswith(".md")):
            raise ValueError("Skill entrypoint must be markdown")
        for fixture in self.fixtures:
            if not matches(self.manifest.input_schema, fixture.input) or not matches(
                self.manifest.output_schema, fixture.expected
            ):
                raise ValueError("Fixture violates declared contract")
        locks = [(item.name, item.version, item.declared_license) for item in self.dependency_lock]
        components = [
            (item.name, item.version, item.declared_license) for item in self.sbom_components
        ]
        if len({name for name, _, _ in locks}) != len(locks) or sorted(locks) != sorted(components):
            raise ValueError("Declared lock and SBOM must agree")
        if len(self.model_dump_json().encode()) > 32768:
            raise ValueError("Capability artifact exceeds bound")
        return self


class Proposal(Contract):
    gap: str = Field(min_length=10, max_length=2000)
    bundle: CapabilityBundle


class Lookup(Contract):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")


class Checks(Contract):
    contract_fixtures: Literal["VALID"]
    python_syntax: Literal["VALID", "INVALID"]
    execution: Literal["NOT_RUN"]
    security: Literal["NOT_VERIFIED"]
    license: Literal["DECLARED_UNVERIFIED"]
    dependencies: Literal["DECLARED_UNVERIFIED"]


class CandidateView(Contract):
    id: str = Field(min_length=36, max_length=36)
    name: str
    version: str
    kind: Literal["tool", "mcp", "skill"]
    state: Literal["QUARANTINED"]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checks: Checks
    created_at: float
    can_invoke: Literal[False]
    untrusted: Literal[True]
    signed_artifacts: list["ArtifactSummary"] = Field(default_factory=list, max_length=5)


class ArtifactSummary(Contract):
    id: str = Field(min_length=36, max_length=36)
    verification_status: Literal["VERIFIED_EVIDENCE", "UNTRUSTED"]
    statement_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    key_id: str = Field(pattern=r"^[0-9a-f]{64}$")
    can_invoke: Literal[False]
    activation_eligible: Literal[False]
    blockers: list[str] = Field(max_length=8)


class CandidateLookup(Contract):
    name: str
    can_invoke: Literal[False]
    candidates: list[CandidateView] = Field(max_length=20)


class CuratedLookup(Contract):
    name: str
    state: Literal["ACTIVE_CURATED"]
    can_invoke: bool
    contract: dict[str, JsonValue]


class VersionConflict(Contract):
    ok: Literal[False]
    error: Literal["version_conflict"]
    can_invoke: Literal[False]


class CheckArgs(Contract):
    bundle_ref: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")


class Finding(Contract):
    code: Literal[
        "configured_secret",
        "invalid_python_syntax",
        "instruction_override_pattern",
        "sensitive_import",
        "dynamic_or_io_call",
        "dunder_introspection",
        "permission_review_required",
        "dependency_audit_required",
    ]
    path: str = Field(min_length=1, max_length=250)
    line: int = Field(ge=0, le=1000000)


class StaticReport(Contract):
    bundle_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    checker_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    classification: Literal["BLOCKED", "REVIEW_REQUIRED"]
    source_executed: Literal[False]
    activation_eligible: Literal[False]
    execution: Literal["NOT_RUN"]
    security: Literal["INCOMPLETE"]
    dependencies: Literal["UNVERIFIED"]
    license: Literal["UNREVIEWED"]
    findings: list[Finding] = Field(max_length=128)
    truncated: bool


class CheckResult(Contract):
    report_ref: str = Field(pattern=r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$")
    report_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    report: StaticReport


FACTORY_DIGEST = hashlib.sha256(
    b"".join(
        Path(__file__).with_name(name).read_bytes()
        for name in (
            "contracts.py",
            "service.py",
            "schema.py",
            "checks.py",
            "static_check.py",
            "verifier.py",
            "artifact_integrity.py",
            "registry.py",
        )
    )
).hexdigest()
CHECKER_DIGEST = FACTORY_DIGEST
INPUTS = {
    "capability_lookup": Lookup,
    "capability_propose": Proposal,
    "capability_check": CheckArgs,
}


def tool_contracts():
    from pydantic import TypeAdapter

    outputs = {
        "capability_lookup": CuratedLookup | CandidateLookup,
        "capability_propose": CandidateView | VersionConflict,
        "capability_check": CheckResult,
    }
    return {
        name: {
            "version": "0.2.0",
            "owner": "caliburn-maintainers",
            "sha256": FACTORY_DIGEST,
            "permissions": [
                "request_static_check" if name == "capability_check" else "quarantine_metadata"
            ],
            "egress": [],
            "side_effects": "append_only_candidate"
            if name == "capability_propose"
            else "durable_static_check_request"
            if name == "capability_check"
            else "none",
            "timeout_seconds": 60,
            "failure_modes": [
                "invalid_arguments",
                "factory_policy_denied",
                "lost_lease",
                "call_timeout",
                "version_conflict",
            ],
            "output_schema": TypeAdapter(output).json_schema(),
        }
        for name, output in outputs.items()
    }


def definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "Find exact-name curated tools or untrusted quarantined candidates; candidate references cannot be invoked"
                if name == "capability_lookup"
                else "Persist source/tests/contracts as an immutable QUARANTINED candidate; never executes, approves or activates source"
                if name == "capability_propose"
                else "Request independent static triage only; waits for a verifier; never executes or approves a candidate",
                "parameters": model.model_json_schema(),
            },
        }
        for name, model in INPUTS.items()
    ]
