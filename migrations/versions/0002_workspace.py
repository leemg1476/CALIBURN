"""M2 inert workspace grants and durable sandbox requests."""

import sqlalchemy as sa
from alembic import op

revision = "0002_workspace"
down_revision = "0001_runtime"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runtime_tasks", sa.Column("workspace_ref", sa.String(36), nullable=True))
    op.create_table(
        "sandbox_workspaces",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("actor", sa.String(100), nullable=False),
        sa.Column("tenant", sa.String(100), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
    )
    op.create_table(
        "sandbox_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("task_id", sa.String(36), sa.ForeignKey("runtime_tasks.id"), nullable=False),
        sa.Column("step_id", sa.String(36), sa.ForeignKey("runtime_steps.id"), nullable=False),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("sandbox_workspaces.id"), nullable=False
        ),
        sa.Column("task_token", sa.String(36), nullable=False),
        sa.Column("operation", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("result", sa.JSON()),
        sa.Column("controller_token", sa.String(36)),
        sa.Column("controller_until", sa.Float()),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("image_digest", sa.String(80)),
        sa.Column("created_at", sa.Float(), nullable=False),
        sa.UniqueConstraint("step_id"),
    )
    op.create_index("ix_sandbox_queue", "sandbox_jobs", ["status", "controller_until"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'caliburn') THEN
            EXECUTE format('REVOKE INSERT, UPDATE, DELETE ON TABLE %I.sandbox_workspaces FROM caliburn', current_schema());
          END IF;
        END $$""")


def downgrade():
    op.drop_table("sandbox_jobs")
    op.drop_table("sandbox_workspaces")
    op.drop_column("runtime_tasks", "workspace_ref")
