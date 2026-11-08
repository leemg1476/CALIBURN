"""Independent inert static triage queue/evidence; no execution authorization."""

from alembic import op
from sqlalchemy import JSON, Column, Float, ForeignKey, Integer, MetaData, String, Table

revision = "0006_factory_checks"
down_revision = "0005_factory"
branch_labels = None
depends_on = None
metadata = MetaData()
for existing in ("runtime_tasks", "runtime_steps", "factory_bundles"):
    Table(existing, metadata, Column("id", String(36), primary_key=True))
bundles = metadata.tables["factory_bundles"]

verifiers = Table(
    "factory_verifiers",
    metadata,
    Column("db_role", String(63), primary_key=True),
    Column("principal", String(80), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("enabled", String(3), nullable=False),
)
check_jobs = Table(
    "factory_check_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("step_id", ForeignKey("runtime_steps.id"), nullable=False, unique=True),
    Column("bundle_id", ForeignKey(bundles.c.id), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("creator_role", String(100), nullable=False),
    Column("bundle_sha256", String(64), nullable=False),
    Column("checker_sha256", String(64), nullable=False),
    Column("state", String(20), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("deadline", Float, nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("lease_token", String(36)),
    Column("lease_until", Float),
    Column("error", String(50)),
)
check_reports = Table(
    "factory_check_reports",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("job_id", ForeignKey(check_jobs.c.id), nullable=False, unique=True),
    Column("lease_token", String(36), nullable=False),
    Column("verifier_role", String(63), nullable=False),
    Column("body", JSON, nullable=False),
    Column("body_sha256", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
)


def upgrade():
    metadata.create_all(op.get_bind(), tables=[verifiers, check_jobs, check_reports])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute("""CREATE FUNCTION factory_verifier_owner() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF NOT EXISTS(SELECT 1 FROM pg_roles r,pg_namespace n WHERE r.rolname=current_user
        AND n.nspname=current_schema() AND (r.rolsuper OR n.nspowner=r.oid)) THEN
        RAISE EXCEPTION 'factory verifier operator required'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_verifiers_owner BEFORE INSERT OR UPDATE OR DELETE ON factory_verifiers FOR EACH ROW EXECUTE FUNCTION factory_verifier_owner()"
    )
    op.execute("""CREATE FUNCTION factory_check_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE t runtime_tasks%ROWTYPE; s runtime_steps%ROWTYPE; b factory_bundles%ROWTYPE;
    BEGIN
      IF TG_OP='INSERT' THEN
        SELECT * INTO t FROM runtime_tasks WHERE id=NEW.task_id;
        SELECT * INTO s FROM runtime_steps WHERE id=NEW.step_id;
        SELECT * INTO b FROM factory_bundles WHERE id=NEW.bundle_id;
        IF t.id IS NULL OR s.id IS NULL OR b.id IS NULL OR s.task_id<>t.id
          OR t.state<>'RUNNING' OR s.status<>'STARTED' OR s.kind<>'TOOL'
          OR t.deadline<=extract(epoch FROM clock_timestamp()) OR t.lease_until<=extract(epoch FROM clock_timestamp())
          OR NOT coalesce(t.policy::jsonb->'tools' ? 'capability_check',false)
          OR (s.input::jsonb->'function'->>'name') IS DISTINCT FROM 'capability_check'
          OR ((s.input::jsonb->'function'->>'arguments')::jsonb->>'bundle_ref') IS DISTINCT FROM b.id
          OR NEW.actor<>t.actor OR NEW.tenant<>t.tenant OR b.actor<>t.actor OR b.tenant<>t.tenant
          OR NEW.bundle_sha256<>b.sha256 OR NEW.deadline<>t.deadline
          OR NEW.state<>'QUEUED' OR NEW.attempts<>0 OR NEW.lease_token IS NOT NULL OR NEW.lease_until IS NOT NULL THEN
          RAISE EXCEPTION 'factory check request scope denied'; END IF;
        NEW.creator_role := current_user;
      ELSE
        IF TG_OP='DELETE' OR NOT EXISTS(SELECT 1 FROM factory_verifiers v
          WHERE v.db_role=current_user AND v.enabled='yes' AND v.tenant=OLD.tenant)
          OR OLD.creator_role=current_user OR EXISTS(SELECT 1 FROM factory_bundles stored_bundle
          WHERE stored_bundle.id=OLD.bundle_id AND stored_bundle.creator_role=current_user) THEN
          RAISE EXCEPTION 'independent factory verifier required'; END IF;
        IF (to_jsonb(NEW)-ARRAY['state','attempts','lease_token','lease_until','error'])
          IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','attempts','lease_token','lease_until','error']) THEN
          RAISE EXCEPTION 'factory check request immutable'; END IF;
        IF OLD.state IN ('FINISHED','FAILED','CANCELLED')
          OR NEW.state NOT IN ('RUNNING','FINISHED','FAILED','CANCELLED')
          OR NEW.attempts<OLD.attempts OR NEW.attempts>OLD.attempts+1 OR NEW.attempts>3
          OR (NEW.state='FINISHED' AND NOT EXISTS(SELECT 1 FROM factory_check_reports r
            WHERE r.job_id=OLD.id AND r.lease_token=OLD.lease_token)) THEN
          RAISE EXCEPTION 'factory check transition denied'; END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_check_jobs_guard BEFORE INSERT OR UPDATE OR DELETE ON factory_check_jobs FOR EACH ROW EXECUTE FUNCTION factory_check_job_guard()"
    )
    op.execute("""CREATE FUNCTION factory_check_report_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE j factory_check_jobs%ROWTYPE; t runtime_tasks%ROWTYPE;
    BEGIN
      SELECT * INTO j FROM factory_check_jobs WHERE id=NEW.job_id;
      SELECT * INTO t FROM runtime_tasks WHERE id=j.task_id;
      IF j.id IS NULL OR t.id IS NULL OR j.state<>'RUNNING' OR NEW.lease_token<>j.lease_token
        OR j.lease_until<=extract(epoch FROM clock_timestamp()) OR t.state<>'RUNNING'
        OR t.deadline<=extract(epoch FROM clock_timestamp()) OR j.creator_role=current_user
        OR NOT coalesce(t.policy::jsonb->'tools' ? 'capability_check',false)
        OR EXISTS(SELECT 1 FROM factory_bundles b WHERE b.id=j.bundle_id AND b.creator_role=current_user)
        OR NOT EXISTS(SELECT 1 FROM factory_verifiers v WHERE v.db_role=current_user AND v.enabled='yes' AND v.tenant=j.tenant)
        OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
        OR has_table_privilege(current_user,format('%I.factory_bundles',current_schema()),'INSERT,UPDATE,DELETE')
        OR (NEW.body::jsonb->>'bundle_sha256') IS DISTINCT FROM j.bundle_sha256
        OR (NEW.body::jsonb->>'checker_sha256') IS DISTINCT FROM j.checker_sha256
        OR (NEW.body::jsonb->>'source_executed') IS DISTINCT FROM 'false'
        OR (NEW.body::jsonb->>'activation_eligible') IS DISTINCT FROM 'false'
        OR NOT coalesce(NEW.body::jsonb->>'classification' IN ('BLOCKED','REVIEW_REQUIRED'),false)
        OR (NEW.body::jsonb->>'execution') IS DISTINCT FROM 'NOT_RUN'
        OR (NEW.body::jsonb->>'security') IS DISTINCT FROM 'INCOMPLETE'
        OR (NEW.body::jsonb->>'dependencies') IS DISTINCT FROM 'UNVERIFIED'
        OR (NEW.body::jsonb->>'license') IS DISTINCT FROM 'UNREVIEWED' THEN
        RAISE EXCEPTION 'factory check report authority denied'; END IF;
      NEW.verifier_role := current_user;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_check_reports_author BEFORE INSERT ON factory_check_reports FOR EACH ROW EXECUTE FUNCTION factory_check_report_guard()"
    )
    op.execute(
        "CREATE TRIGGER factory_check_reports_immutable BEFORE UPDATE OR DELETE ON factory_check_reports FOR EACH ROW EXECUTE FUNCTION factory_immutable()"
    )
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
      EXECUTE format('REVOKE ALL ON %I.factory_verifiers,%I.factory_check_jobs,%I.factory_check_reports FROM caliburn',current_schema(),current_schema(),current_schema());
      EXECUTE format('GRANT SELECT ON %I.factory_verifiers,%I.factory_check_jobs,%I.factory_check_reports TO caliburn',current_schema(),current_schema(),current_schema());
      EXECUTE format('GRANT INSERT ON %I.factory_check_jobs TO caliburn',current_schema());
    END IF; END $$""")


def downgrade():
    for name in ("factory_check_reports", "factory_check_jobs", "factory_verifiers"):
        op.drop_table(name)
    if op.get_bind().dialect.name == "postgresql":
        for name in (
            "factory_check_report_guard",
            "factory_check_job_guard",
            "factory_verifier_owner",
        ):
            op.execute("DROP FUNCTION " + name + "()")
