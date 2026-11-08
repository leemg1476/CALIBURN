"""Trusted-host finite-vector oracle. Never import candidate code here."""

import json
import math
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from caliburn.sandbox.contracts import TestRun
from caliburn.tool_factory.contracts import Contract, digest

PLAN_FILE = "caliburn_host_oracle.json"
SUITE = "repeat-order-replay-v1"
SESSION_COUNT = 4
REPETITIONS = 2


class OracleCase(Contract):
    name: str = Field(min_length=1, max_length=80)
    input: dict[str, JsonValue]
    expected: JsonValue


class OraclePlan(Contract):
    version: Literal["host-oracle-v1", "host-oracle-v2"] = "host-oracle-v2"
    profile: Literal["repeat-order-replay-v1"] = SUITE
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
    version: Literal["host-oracle-v1", "host-oracle-v2"] = "host-oracle-v2"
    plan_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total: int = Field(ge=1, le=8)
    checked: int = Field(ge=0, le=8)
    status: Literal["PASSED", "FAILED"]
    profile: Literal["repeat-order-replay-v1"] | None = None
    sessions_total: int = Field(default=0, ge=0, le=4)
    sessions_checked: int = Field(default=0, ge=0, le=4)
    observations_total: int = Field(default=0, ge=0, le=64)
    observations_checked: int = Field(default=0, ge=0, le=64)

    @model_validator(mode="after")
    def consistent(self):
        if self.checked > self.total or (self.status == "PASSED" and self.checked != self.total):
            raise ValueError("Incomplete oracle proof")
        if self.version == "host-oracle-v2" and (
            self.profile != SUITE
            or self.sessions_total != SESSION_COUNT
            or self.observations_total != self.total * SESSION_COUNT * REPETITIONS
            or self.sessions_checked > self.sessions_total
            or self.observations_checked > self.observations_total
            or (
                self.status == "PASSED"
                and (
                    self.sessions_checked != self.sessions_total
                    or self.observations_checked != self.observations_total
                )
            )
        ):
            raise ValueError("Incomplete repeat/order/replay proof")
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


def require_proof(binding, isolation, *, current=False):
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
    if (current or binding.get("version") == "factory-execution-v3") and (
        binding.get("version") != "factory-execution-v3"
        or proof.version != "host-oracle-v2"
        or binding.get("oracle_profile") != SUITE
        or binding.get("oracle_sessions") != proof.sessions_total
        or binding.get("oracle_observations") != proof.observations_total
    ):
        raise ValueError("Repeat/order/replay evidence mismatch")
    return proof


def plan_digest(plan):
    return digest(plan.model_dump())


def sessions(plan):
    """Four fresh sessions, each repeating every input twice in a bound order."""
    if plan.version != "host-oracle-v2":
        raise ValueError("Legacy plans require a new independent review")
    forward = list(range(len(plan.cases)))
    reverse = list(reversed(forward))
    return [
        [i for i in order for _ in range(REPETITIONS)]
        for order in (forward, forward, reverse, reverse)
    ]
