"""Trusted-host finite-vector oracle. Never import candidate code here."""

import json
import math
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from caliburn.sandbox.contracts import TestRun
from caliburn.tool_factory.contracts import Contract, digest

PLAN_FILE = "caliburn_host_oracle.json"


class OracleCase(Contract):
    name: str = Field(min_length=1, max_length=80)
    input: dict[str, JsonValue]
    expected: JsonValue


class OraclePlan(Contract):
    version: Literal["host-oracle-v1"] = "host-oracle-v1"
    case_source: Literal["bundle_declared", "operator"] = "bundle_declared"
    entrypoint: str = Field(max_length=240)
    cases: list[OracleCase] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def bounded(self):
        if len(self.model_dump_json().encode()) > 32768 or len({c.name for c in self.cases}) != len(
            self.cases
        ):
            raise ValueError("Invalid bounded oracle plan")
        # Reject nonfinite values nested anywhere; JSON serialization is never executable.
        json.dumps(self.model_dump(), allow_nan=False)
        return self


class OracleProof(Contract):
    version: Literal["host-oracle-v1"] = "host-oracle-v1"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total: int = Field(ge=1, le=8)
    checked: int = Field(ge=0, le=8)
    status: Literal["PASSED", "FAILED"]

    @model_validator(mode="after")
    def consistent(self):
        if self.checked > self.total or (self.status == "PASSED" and self.checked != self.total):
            raise ValueError("Incomplete oracle proof")
        return self


def parse_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate key")
            result[key] = value
        return result

    def invalid(_):
        raise ValueError("Nonfinite JSON")

    if len(raw) > 32768:
        raise ValueError("Oracle JSON too large")
    try:
        value = json.loads(raw, object_pairs_hook=pairs, parse_constant=invalid)
        stack = [(value, 0)]
        while stack:
            item, depth = stack.pop()
            if depth > 64:
                raise ValueError("Oracle JSON too deep")
            if isinstance(item, float) and not math.isfinite(item):
                raise ValueError("Nonfinite JSON")
            if isinstance(item, dict):
                stack.extend((v, depth + 1) for v in item.values())
            elif isinstance(item, list):
                stack.extend((v, depth + 1) for v in item)
        return value
    except RecursionError:
        raise ValueError("Oracle JSON too deep") from None


def read_plan(files):
    return OraclePlan.model_validate(parse_json(files[PLAN_FILE]))


def same(actual, expected):
    """Type-strict JSON observation; bool is not int and object keys must match."""
    if type(actual) is not type(expected):
        return False
    if isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            same(actual[k], v) for k, v in expected.items()
        )
    if isinstance(expected, list):
        return len(actual) == len(expected) and all(same(a, b) for a, b in zip(actual, expected))
    if isinstance(expected, float) and not math.isfinite(expected):
        return False
    return actual == expected


def require_proof(binding, isolation):
    proof = OracleProof.model_validate(isolation.get("host_oracle"))
    child = TestRun.model_validate(isolation.get("child_test_run"))
    if (
        child.status != "PASSED"
        or child.plan_sha256 != binding.get("child_plan_sha256")
        or child.source_sha256 != binding.get("source_sha256")
    ):
        raise ValueError("Child evidence mismatch")
    if proof.plan_sha256 != binding.get("oracle_sha256") or proof.total != binding.get(
        "oracle_cases"
    ):
        raise ValueError("Oracle evidence mismatch")
    return proof


def plan_digest(plan):
    return digest(plan.model_dump())
