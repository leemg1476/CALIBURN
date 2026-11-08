"""Durable task API contracts; clients cannot choose actor, tenant or policy."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class Limits(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    max_steps: int = Field(default=6, ge=1, le=40)
    max_tool_calls: int = Field(default=16, ge=0, le=200)
    max_tokens: int = Field(default=64000, ge=1, le=1000000)
    max_cost: float = Field(default=0, ge=0, le=100)
    timeout_seconds: float = Field(default=300, ge=0.1, le=86400)
    call_timeout_seconds: float = Field(default=60, ge=0.05, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)


class Submit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt: str = Field(min_length=1, max_length=20000)
    workspace_ref: str | None = Field(default=None, min_length=36, max_length=36)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    limits: Limits = Field(default_factory=Limits)
    capabilities: (
        list[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{2,63}$", max_length=64)]] | None
    ) = Field(default=None, max_length=8)


class Task(BaseModel):
    id: str
    state: Literal[
        "QUEUED",
        "RUNNING",
        "PAUSED",
        "WAITING_APPROVAL",
        "COMPLETED",
        "FAILED",
        "CANCELLED",
        "TIMED_OUT",
    ]
    prompt: str
    workspace_ref: str | None = None
    result: str | None = None
    error: str | None = None
    model_calls: int
    tool_calls: int
    reserved_tokens: int
    reserved_cost: float
    sequence: int
    created_at: float
    updated_at: float


class RunView(BaseModel):
    id: str
    worker: str
    started_at: float
    ended_at: float | None
    outcome: str | None


class StepView(BaseModel):
    id: str
    ordinal: int
    run_id: str
    kind: str
    status: str
    attempts: int
    tool_name: str | None
    input_sha256: str
    output_sha256: str | None


class History(BaseModel):
    limits: Limits
    deadline: float | None
    runs: list[RunView]
    steps: list[StepView]
    next_step: int | None
    next_run_offset: int | None
