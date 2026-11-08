"""Immutable proposal/review records; reviewer mappings are operator owned."""

from sqlalchemy import JSON, Column, Float, ForeignKey, String, Table, UniqueConstraint

from caliburn.sandbox.schema import metadata

candidates = Table(
    "policy_candidates",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("parent_id", ForeignKey("policy_candidates.id"), nullable=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("step_id", ForeignKey("runtime_steps.id"), nullable=False, unique=True),
    Column("workspace_id", ForeignKey("sandbox_workspaces.id"), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("creator_role", String(100), nullable=False),
    Column("base_digest", String(64), nullable=False),
    Column("artifact_digest", String(64), nullable=False),
    Column("files", JSON, nullable=False),
    Column("patch", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
)
plans = Table(
    "policy_test_plans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("workspace_id", ForeignKey("sandbox_workspaces.id"), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("owner_role", String(100), nullable=False),
    Column("files", JSON, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("image_digest", String(80), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)
reviewers = Table(
    "policy_reviewers",
    metadata,
    Column("db_role", String(63), primary_key=True),
    Column("principal", String(80), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("enabled", String(3), nullable=False),
)
requests = Table(
    "policy_review_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("candidate_id", ForeignKey(candidates.c.id), nullable=False),
    Column("plan_id", ForeignKey(plans.c.id), nullable=False),
    Column("call_key", String(64), nullable=False),
    Column("creator_role", String(100), nullable=False),
    Column("binding", JSON, nullable=False),
    Column("digest", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    UniqueConstraint("task_id", "call_key"),
)
decisions = Table(
    "policy_review_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("request_id", ForeignKey(requests.c.id), nullable=False, unique=True),
    Column("decision", String(10), nullable=False),
    Column("reviewer_role", String(100), nullable=False),
    Column("binding_digest", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)
revocations = Table(
    "policy_review_revocations",
    metadata,
    Column("request_id", ForeignKey(requests.c.id), primary_key=True),
    Column("reviewer_role", String(100), nullable=False),
    Column("created_at", Float, nullable=False),
)
