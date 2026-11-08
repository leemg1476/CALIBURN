"""M1 durable runtime initial schema; existing M0 SQLite tables are untouched."""

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)

metadata = MetaData()
tasks = Table(
    "runtime_tasks",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("idempotency_key", String(200), nullable=False),
    Column("request_hash", String(64), nullable=False),
    Column("prompt", Text, nullable=False),
    Column("state", String(30), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("updated_at", Float, nullable=False),
    Column("deadline", Float),
    Column("limits", JSON, nullable=False),
    Column("policy", JSON, nullable=False),
    Column("messages", JSON, nullable=False),
    Column("result", Text),
    Column("error", String(100)),
    Column("sequence", Integer, nullable=False, default=0),
    Column("model_calls", Integer, nullable=False, default=0),
    Column("tool_calls", Integer, nullable=False, default=0),
    Column("reserved_tokens", Integer, nullable=False, default=0),
    Column("reserved_cost", Float, nullable=False, default=0),
    Column("lease_token", String(36)),
    Column("lease_owner", String(100)),
    Column("lease_until", Float),
    Column("run_id", String(36)),
    UniqueConstraint("tenant", "actor", "idempotency_key"),
)
Index("ix_runtime_queue", tasks.c.state, tasks.c.lease_until, tasks.c.created_at)
runs = Table(
    "runtime_runs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("worker", String(100), nullable=False),
    Column("started_at", Float, nullable=False),
    Column("ended_at", Float),
    Column("outcome", String(30)),
)
steps = Table(
    "runtime_steps",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("run_id", ForeignKey(runs.c.id), nullable=False),
    Column("ordinal", Integer, nullable=False),
    Column("kind", String(10), nullable=False),
    Column("status", String(20), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("input", JSON, nullable=False),
    Column("output", JSON),
    UniqueConstraint("task_id", "ordinal"),
)
events = Table(
    "runtime_events",
    metadata,
    Column("task_id", ForeignKey(tasks.c.id), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("timestamp", Float, nullable=False),
    Column("actor", String(100), nullable=False),
    Column("type", String(50), nullable=False),
    Column("run_id", String(36)),
    Column("payload", JSON, nullable=False),
)
attachments = Table(
    "runtime_attachments",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey(tasks.c.id), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("media_type", String(100), nullable=False),
    Column("content", Text, nullable=False),
)

revision = "0001_runtime"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind())
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION reject_runtime_event_mutation() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'runtime events are append-only'; END $$""")
        op.execute("""CREATE TRIGGER runtime_events_immutable BEFORE UPDATE OR DELETE
        ON runtime_events FOR EACH ROW EXECUTE FUNCTION reject_runtime_event_mutation()""")


def downgrade():
    metadata.drop_all(op.get_bind())
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION reject_runtime_event_mutation()")
