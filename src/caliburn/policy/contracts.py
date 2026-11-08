"""Review requests carry references only; no user-supplied approver or authority flag."""

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ReviewArgs(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    candidate_ref: str = Field(min_length=36, max_length=36)
    plan_ref: str = Field(min_length=36, max_length=36)


class ReviewEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review_status: Literal["APPROVED_FOR_SANDBOX_TEST"]
    request_ref: str = Field(min_length=36, max_length=36)
    binding_sha256: str = Field(pattern="^[a-f0-9]{64}$")
    scope: Literal["sandbox_test_only"]
    source_executed: Literal[False]


class ReviewResult(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    ok: Literal[True]
    data: ReviewEvidence


REVIEW_TOOL_DIGEST = hashlib.sha256(
    Path(__file__).read_bytes()
    + Path(__file__).with_name("review.py").read_bytes()
    + Path(__file__).with_name("schema.py").read_bytes()
).hexdigest()


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def definition():
    return {
        "type": "function",
        "function": {
            "name": "repo_request_review",
            "description": "Request independent review of exact candidate/test-plan hashes. Pauses task; does not execute source or publish a tool.",
            "parameters": ReviewArgs.model_json_schema(),
        },
    }


REVIEW_MANIFEST = {
    "name": "repo_request_review",
    "version": "1.0.0",
    "digest": REVIEW_TOOL_DIGEST,
    "owner": "caliburn-maintainers",
    "permissions": ["request_review"],
    "input_schema": ReviewArgs.model_json_schema(),
    "output_schema": ReviewResult.model_json_schema(),
    "network": [],
    "secret_scopes": [],
    "failure_modes": ["scope_denied", "expired", "rejected", "revoked"],
    "timeout_seconds": 0,
    "side_effects": "durable_review_request_and_task_pause",
}
