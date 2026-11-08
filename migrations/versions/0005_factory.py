"""Immutable unapproved artifacts and fenced proposal receipts, separate from activation."""

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

metadata = MetaData()
for existing in ("runtime_tasks", "runtime_steps"):
    Table(existing, metadata, Column("id", String(36), primary_key=True))

bundles = Table(
    "factory_bundles",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("origin_task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("origin_step_id", ForeignKey("runtime_steps.id"), nullable=False, unique=True),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("creator_role", String(100), nullable=False),
    Column("name", String(64), nullable=False),
    Column("version", String(30), nullable=False),
    Column("kind", String(10), nullable=False),
    Column("state", String(20), nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("payload", JSON, nullable=False),
    Column("checks", JSON, nullable=False),
    Column("created_at", Float, nullable=False),
    CheckConstraint("state = 'QUARANTINED'", name="ck_factory_quarantine_only"),
    UniqueConstraint("actor", "tenant", "name", "version", name="uq_factory_version"),
)
proposals = Table(
    "factory_proposals",
    metadata,
    Column("step_id", ForeignKey("runtime_steps.id"), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("bundle_id", ForeignKey(bundles.c.id), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("gap", String(2000), nullable=False),
    Column("request_sha256", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
)


from alembic import op

revision = "0005_factory"
down_revision = "0004_candidate_parent"
branch_labels = None
depends_on = None


def upgrade():
    metadata.create_all(op.get_bind(), tables=[bundles, proposals])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION factory_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'factory record is immutable'; END $$""")
        op.execute("""CREATE FUNCTION factory_scope() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE t runtime_tasks%ROWTYPE; s runtime_steps%ROWTYPE;
        BEGIN
          IF TG_TABLE_NAME='factory_bundles' THEN
            SELECT * INTO t FROM runtime_tasks WHERE id=NEW.origin_task_id;
            SELECT * INTO s FROM runtime_steps WHERE id=NEW.origin_step_id;
            NEW.creator_role := current_user;
          ELSE
            SELECT * INTO t FROM runtime_tasks WHERE id=NEW.task_id;
            SELECT * INTO s FROM runtime_steps WHERE id=NEW.step_id;
            IF NOT EXISTS(SELECT 1 FROM factory_bundles b WHERE b.id=NEW.bundle_id
              AND b.actor=t.actor AND b.tenant=t.tenant) THEN
              RAISE EXCEPTION 'factory candidate scope denied'; END IF;
          END IF;
          IF t.id IS NULL OR s.id IS NULL OR s.task_id<>t.id OR t.state<>'RUNNING'
            OR s.kind<>'TOOL' OR s.status<>'STARTED'
            OR t.lease_until<=extract(epoch FROM clock_timestamp())
            OR t.deadline<=extract(epoch FROM clock_timestamp())
            OR NOT coalesce(t.policy::jsonb->'tools' ? 'capability_propose',false)
            OR (s.input::jsonb->'function'->>'name') IS DISTINCT FROM 'capability_propose'
            OR NEW.actor<>t.actor OR NEW.tenant<>t.tenant THEN
              RAISE EXCEPTION 'factory task scope denied'; END IF;
          RETURN NEW;
        END $$""")
        for name in ("factory_bundles", "factory_proposals"):
            op.execute(
                f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION factory_immutable()"
            )
            op.execute(
                f"CREATE TRIGGER {name}_scope BEFORE INSERT ON {name} FOR EACH ROW EXECUTE FUNCTION factory_scope()"
            )
        op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
          EXECUTE format('GRANT SELECT,INSERT ON %I.factory_bundles,%I.factory_proposals TO caliburn',current_schema(),current_schema());
          EXECUTE format('REVOKE UPDATE,DELETE ON %I.factory_bundles,%I.factory_proposals FROM caliburn',current_schema(),current_schema());
        END IF; END $$""")


def downgrade():
    op.drop_table("factory_proposals")
    op.drop_table("factory_bundles")
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP FUNCTION factory_scope()")
        op.execute("DROP FUNCTION factory_immutable()")
