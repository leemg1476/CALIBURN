"""Factory execution is separately approved sandbox testing, never activation."""

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, JsonValue, model_validator

from caliburn.sandbox.contracts import TestRun
from caliburn.tool_factory.contracts import Contract

UUID = r"^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$"
SHA = r"^[0-9a-f]{64}$"


class ExecutionReviewArgs(Contract):
    plan_ref: str = Field(pattern=UUID)


class ExecuteArgs(Contract):
    request_ref: str = Field(pattern=UUID)


class ExecutionAdmission(Contract):
    request_ref: str = Field(pattern=UUID)
    binding_sha256: str = Field(pattern=SHA)
    status: Literal["APPROVED_FOR_FACTORY_SANDBOX_TEST"]
    scope: Literal["factory_sandbox_test_only"]
    source_executed: Literal[False]
    production_approved: Literal[False]


class ExecutionEvidence(Contract):
    executor_role: str = Field(min_length=1, max_length=63)
    request_ref: str = Field(pattern=UUID)
    binding_sha256: str = Field(pattern=SHA)
    image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    run: TestRun
    source_executed: Literal[True]
    production_approved: Literal[False]
    security: Literal["INCOMPLETE"]
    license: Literal["UNREVIEWED"]


class ExecutionResult(Contract):
    ok: bool
    data: ExecutionEvidence | None = None
    error: str | None = Field(default=None, max_length=100)
    isolation: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.ok != (self.data is not None)
            or (self.ok and self.error is not None)
            or (not self.ok and not self.error)
        ):
            raise ValueError("Inconsistent Factory execution result")
        return self


EXEC_INPUTS = {
    "capability_request_execution": ExecutionReviewArgs,
    "capability_execute_tests": ExecuteArgs,
}
EXEC_DIGEST = hashlib.sha256(
    b"".join(
        Path(__file__).with_name(name).read_bytes()
        for name in (
            "execution_contracts.py",
            "qualification.py",
            "execution_queue.py",
            "execution_control.py",
            "schema.py",
        )
    )
    + b"".join(
        Path(__file__).parent.parent.joinpath("sandbox", name).read_bytes()
        for name in ("control.py", "runner.py", "test_runner.py", "test_check.py")
    )
).hexdigest()


def definitions():
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": "Request independent approval for exact Factory bundle/static report/plan/image; pauses task and never executes source"
                if name == "capability_request_execution"
                else "Run only independently approved Factory sandbox tests; passing does not activate or approve production",
                "parameters": model.model_json_schema(),
            },
        }
        for name, model in EXEC_INPUTS.items()
    ]


EXEC_MANIFESTS = {
    name: {
        "name": name,
        "version": "0.1.0",
        "owner": "caliburn-maintainers",
        "sha256": EXEC_DIGEST,
        "input_schema": model.model_json_schema(),
        "output_schema": (
            ExecutionAdmission if name == "capability_request_execution" else ExecutionResult
        ).model_json_schema(),
        "permissions": [
            "request_factory_execution"
            if name == "capability_request_execution"
            else "execute_factory_tests"
        ],
        "egress": [],
        "secret_scopes": [],
        "timeout_seconds": 0 if name == "capability_request_execution" else 20,
        "side_effects": "durable_independent_review_wait"
        if name == "capability_request_execution"
        else "approved_disposable_sandbox_tests",
        "failure_modes": [
            "scope_denied",
            "expired",
            "rejected",
            "revoked",
            "execution_failed",
            "timeout",
            "output_limit",
            "lost_lease",
        ],
    }
    for name, model in EXEC_INPUTS.items()
}
