"""Separate fixed digest workspace snapshots and typed sandbox dispatch queue."""

from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Table,
    UniqueConstraint,
)

from caliburn.runtime.schema import metadata

workspaces = Table(
    "sandbox_workspaces",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("digest", String(64), nullable=False),
    Column("files", JSON, nullable=False),
    Column("permissions", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("provenance", JSON, nullable=False),
)
jobs = Table(
    "sandbox_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("step_id", ForeignKey("runtime_steps.id"), nullable=False),
    Column("workspace_id", ForeignKey(workspaces.c.id), nullable=False),
    Column("task_token", String(36), nullable=False),
    Column("operation", JSON, nullable=False),
    Column("status", String(20), nullable=False),
    Column("result", JSON),
    Column("controller_token", String(36)),
    Column("controller_until", Float),
    Column("attempts", Integer, nullable=False),
    Column("image_digest", String(80)),
    Column("created_at", Float, nullable=False),
    UniqueConstraint("step_id"),
)
Index("ix_sandbox_queue", jobs.c.status, jobs.c.controller_until)
