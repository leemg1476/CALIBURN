"""Separate Factory sandbox approval and execution authority; no activation."""

from alembic import op
from sqlalchemy import (
    JSON,
    Column,
    Float,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    UniqueConstraint,
)

revision = "0007_factory_execution"
down_revision = "0006_factory_checks"
branch_labels = None
depends_on = None
metadata = MetaData()
for name in ("runtime_tasks", "runtime_steps", "factory_bundles", "factory_check_reports"):
    Table(name, metadata, Column("id", String(36), primary_key=True))
bundles = metadata.tables["factory_bundles"]
check_reports = metadata.tables["factory_check_reports"]
exec_roles = Table(
    "factory_exec_roles",
    metadata,
    Column("db_role", String(63), primary_key=True),
    Column("principal", String(80), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("kind", String(10), nullable=False),
    Column("enabled", String(3), nullable=False),
)
exec_plans = Table(
    "factory_exec_plans",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("bundle_id", ForeignKey(bundles.c.id), nullable=False),
    Column("report_id", ForeignKey(check_reports.c.id), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("owner_role", String(100), nullable=False),
    Column("files", JSON, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("image_digest", String(80), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)
exec_requests = Table(
    "factory_exec_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("plan_id", ForeignKey(exec_plans.c.id), nullable=False),
    Column("call_key", String(64), nullable=False),
    Column("creator_role", String(100), nullable=False),
    Column("binding", JSON, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    UniqueConstraint("task_id", "call_key"),
)
exec_decisions = Table(
    "factory_exec_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("request_id", ForeignKey(exec_requests.c.id), nullable=False, unique=True),
    Column("reviewer_role", String(63), nullable=False),
    Column("decision", String(10), nullable=False),
    Column("binding_sha256", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)
exec_revocations = Table(
    "factory_exec_revocations",
    metadata,
    Column("request_id", ForeignKey(exec_requests.c.id), primary_key=True),
    Column("reviewer_role", String(63), nullable=False),
    Column("created_at", Float, nullable=False),
)
exec_jobs = Table(
    "factory_exec_jobs",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("step_id", ForeignKey("runtime_steps.id"), nullable=False, unique=True),
    Column("request_id", ForeignKey(exec_requests.c.id), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("creator_role", String(100), nullable=False),
    Column("binding_sha256", String(64), nullable=False),
    Column("state", String(20), nullable=False),
    Column("attempts", Integer, nullable=False, default=0),
    Column("created_at", Float, nullable=False),
    Column("lease_token", String(36)),
    Column("lease_until", Float),
    Column("result", JSON),
    Column("result_sha256", String(64)),
    Column("executor_role", String(63)),
)


def upgrade():
    metadata.create_all(
        op.get_bind(),
        tables=[exec_roles, exec_plans, exec_requests, exec_decisions, exec_revocations, exec_jobs],
    )
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE TRIGGER factory_exec_roles_owner BEFORE INSERT OR UPDATE OR DELETE ON factory_exec_roles FOR EACH ROW EXECUTE FUNCTION factory_verifier_owner()"
    )
    op.execute(
        "CREATE TRIGGER factory_exec_plans_owner BEFORE INSERT ON factory_exec_plans FOR EACH ROW EXECUTE FUNCTION factory_verifier_owner()"
    )
    for name in (
        "factory_exec_plans",
        "factory_exec_requests",
        "factory_exec_decisions",
        "factory_exec_revocations",
    ):
        op.execute(
            f"CREATE TRIGGER {name}_immutable BEFORE UPDATE OR DELETE ON {name} FOR EACH ROW EXECUTE FUNCTION factory_immutable()"
        )
    op.execute("""CREATE FUNCTION factory_exec_request_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE t runtime_tasks%ROWTYPE; p factory_exec_plans%ROWTYPE;
    BEGIN
      SELECT * INTO t FROM runtime_tasks WHERE id=NEW.task_id;
      SELECT * INTO p FROM factory_exec_plans WHERE id=NEW.plan_id;
      IF t.id IS NULL OR p.id IS NULL OR t.state<>'RUNNING'
        OR t.lease_until<=extract(epoch FROM clock_timestamp()) OR t.deadline<=extract(epoch FROM clock_timestamp())
        OR p.actor<>t.actor OR p.tenant<>t.tenant OR p.expires_at<=extract(epoch FROM clock_timestamp())
        OR NEW.expires_at>least(p.expires_at,t.deadline)
        OR NOT coalesce(t.policy::jsonb->'tools' ? 'capability_request_execution',false)
        OR NOT coalesce(t.policy::jsonb->'tools' ? 'capability_execute_tests',false)
        OR (NEW.binding::jsonb->>'implementation_sha256') IS DISTINCT FROM (t.policy::jsonb->>'exec_digest')
        OR (NEW.binding::jsonb->>'plan_ref') IS DISTINCT FROM p.id
        OR (NEW.binding::jsonb->>'plan_sha256') IS DISTINCT FROM p.sha256
        OR (NEW.binding::jsonb->>'image_digest') IS DISTINCT FROM p.image_digest
        OR (NEW.binding::jsonb->>'task_id') IS DISTINCT FROM t.id
        OR (NEW.binding::jsonb->>'scope') IS DISTINCT FROM 'factory_sandbox_test_only' THEN
        RAISE EXCEPTION 'factory execution request scope denied'; END IF;
      NEW.creator_role:=current_user;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_exec_request_author BEFORE INSERT ON factory_exec_requests FOR EACH ROW EXECUTE FUNCTION factory_exec_request_guard()"
    )
    op.execute("""CREATE FUNCTION factory_exec_reviewer_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r factory_exec_requests%ROWTYPE; t runtime_tasks%ROWTYPE; p factory_exec_plans%ROWTYPE; b factory_bundles%ROWTYPE; s factory_check_reports%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM factory_exec_requests WHERE id=NEW.request_id;
      SELECT * INTO t FROM runtime_tasks WHERE id=r.task_id;
      SELECT * INTO p FROM factory_exec_plans WHERE id=r.plan_id;
      SELECT * INTO b FROM factory_bundles WHERE id=p.bundle_id;
      SELECT * INTO s FROM factory_check_reports WHERE id=p.report_id;
      IF r.id IS NULL OR t.id IS NULL OR p.id IS NULL OR b.id IS NULL OR s.id IS NULL
        OR NOT EXISTS(SELECT 1 FROM factory_exec_roles a WHERE a.db_role=current_user AND a.kind='REVIEWER' AND a.enabled='yes' AND a.tenant=t.tenant AND a.principal<>t.actor)
        OR current_user IN (r.creator_role,b.creator_role,p.owner_role,s.verifier_role)
        OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
        OR has_table_privilege(current_user,format('%I.factory_bundles',current_schema()),'INSERT,UPDATE,DELETE') THEN
        RAISE EXCEPTION 'independent Factory execution reviewer required'; END IF;
      IF TG_TABLE_NAME='factory_exec_decisions' THEN
        IF t.state<>'WAITING_APPROVAL' OR NEW.binding_sha256<>r.sha256
          OR NEW.decision NOT IN ('APPROVE','REJECT') OR NEW.expires_at>r.expires_at
          OR NEW.expires_at<=extract(epoch FROM clock_timestamp()) OR r.expires_at<=extract(epoch FROM clock_timestamp()) THEN
          RAISE EXCEPTION 'factory execution decision scope denied'; END IF;
      ELSE
        IF NOT EXISTS(SELECT 1 FROM factory_exec_decisions d WHERE d.request_id=r.id) THEN
          RAISE EXCEPTION 'factory execution decision unavailable'; END IF;
      END IF;
      NEW.reviewer_role:=current_user;
      RETURN NEW;
    END $$""")
    for name in ("factory_exec_decisions", "factory_exec_revocations"):
        op.execute(
            f"CREATE TRIGGER {name}_author BEFORE INSERT ON {name} FOR EACH ROW EXECUTE FUNCTION factory_exec_reviewer_guard()"
        )
    op.execute("""CREATE FUNCTION factory_exec_job_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r factory_exec_requests%ROWTYPE; t runtime_tasks%ROWTYPE; s runtime_steps%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM factory_exec_requests WHERE id=NEW.request_id;
      SELECT * INTO t FROM runtime_tasks WHERE id=NEW.task_id;
      IF TG_OP='INSERT' THEN
        SELECT * INTO s FROM runtime_steps WHERE id=NEW.step_id;
        IF r.id IS NULL OR t.id IS NULL OR s.id IS NULL OR r.task_id<>t.id OR s.task_id<>t.id
          OR s.status<>'STARTED' OR s.kind<>'TOOL' OR t.state<>'RUNNING'
          OR t.lease_until<=extract(epoch FROM clock_timestamp()) OR t.deadline<=extract(epoch FROM clock_timestamp())
          OR NEW.binding_sha256<>r.sha256 OR NEW.tenant<>t.tenant
          OR (s.input::jsonb->'function'->>'name') IS DISTINCT FROM 'capability_execute_tests'
          OR ((s.input::jsonb->'function'->>'arguments')::jsonb->>'request_ref') IS DISTINCT FROM r.id
          OR NEW.state<>'QUEUED' OR NEW.attempts<>0 OR NEW.lease_token IS NOT NULL OR NEW.result IS NOT NULL
          OR NOT EXISTS(SELECT 1 FROM factory_exec_decisions d JOIN factory_exec_roles a ON a.db_role=d.reviewer_role
            WHERE d.request_id=r.id AND d.decision='APPROVE' AND d.binding_sha256=r.sha256
              AND d.expires_at>extract(epoch FROM clock_timestamp()) AND a.enabled='yes' AND a.kind='REVIEWER' AND a.tenant=t.tenant)
          OR EXISTS(SELECT 1 FROM factory_exec_revocations v WHERE v.request_id=r.id) THEN
          RAISE EXCEPTION 'Factory execution job admission denied'; END IF;
        NEW.creator_role:=current_user;
      ELSE
        IF TG_OP='DELETE' OR OLD.state IN ('COMPLETED','DENIED')
          OR NOT EXISTS(SELECT 1 FROM factory_exec_roles a WHERE a.db_role=current_user AND a.kind='EXECUTOR' AND a.enabled='yes' AND a.tenant=OLD.tenant)
          OR current_user=OLD.creator_role
          OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
          OR has_table_privilege(current_user,format('%I.factory_bundles',current_schema()),'INSERT,UPDATE,DELETE') THEN
          RAISE EXCEPTION 'independent Factory executor required'; END IF;
        IF (to_jsonb(NEW)-ARRAY['state','attempts','lease_token','lease_until','result','result_sha256','executor_role'])
          IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','attempts','lease_token','lease_until','result','result_sha256','executor_role'])
          OR NEW.attempts<OLD.attempts OR NEW.attempts>OLD.attempts+1 OR NEW.attempts>3
          OR NEW.state NOT IN ('RUNNING','COMPLETED','DENIED') THEN
          RAISE EXCEPTION 'Factory execution job immutable'; END IF;
        IF NEW.state='RUNNING' AND NEW.lease_token IS DISTINCT FROM OLD.lease_token THEN
          IF OLD.state='RUNNING' AND OLD.lease_until>extract(epoch FROM clock_timestamp()) THEN
            RAISE EXCEPTION 'Factory executor lease already owned'; END IF;
          NEW.executor_role:=current_user;
        ELSIF NEW.state<>'DENIED' AND OLD.executor_role IS DISTINCT FROM current_user THEN
          RAISE EXCEPTION 'Factory executor lease owner denied'; END IF;
        IF NEW.state='COMPLETED' THEN
          IF OLD.lease_until<=extract(epoch FROM clock_timestamp()) OR t.state<>'RUNNING'
            OR t.deadline<=extract(epoch FROM clock_timestamp()) OR t.lease_until<=extract(epoch FROM clock_timestamp())
            OR NEW.result IS NULL OR NEW.result_sha256 IS NULL
            OR EXISTS(SELECT 1 FROM factory_exec_revocations v WHERE v.request_id=r.id) THEN
            RAISE EXCEPTION 'Factory execution result unavailable'; END IF;
          IF NEW.result::jsonb->>'ok'='true' AND (
            (NEW.result::jsonb->'data'->>'production_approved') IS DISTINCT FROM 'false'
            OR (NEW.result::jsonb->'data'->>'source_executed') IS DISTINCT FROM 'true'
            OR (NEW.result::jsonb->'data'->>'binding_sha256') IS DISTINCT FROM r.sha256
            OR (NEW.result::jsonb->'data'->>'request_ref') IS DISTINCT FROM r.id
            OR (NEW.result::jsonb->'data'->>'executor_role') IS DISTINCT FROM current_user
            OR (NEW.result::jsonb->'data'->>'image_digest') IS DISTINCT FROM (r.binding::jsonb->>'image_digest')
            OR (NEW.result::jsonb->'data'->'run'->>'source_sha256') IS DISTINCT FROM (r.binding::jsonb->>'source_sha256')
            OR (NEW.result::jsonb->'data'->'run'->>'plan_sha256') IS DISTINCT FROM (r.binding::jsonb->>'plan_sha256')
            OR (NEW.result::jsonb->'data'->>'security') IS DISTINCT FROM 'INCOMPLETE'
            OR (NEW.result::jsonb->'data'->>'license') IS DISTINCT FROM 'UNREVIEWED') THEN
            RAISE EXCEPTION 'Factory execution result scope denied'; END IF;
        END IF;
      END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_exec_jobs_guard BEFORE INSERT OR UPDATE OR DELETE ON factory_exec_jobs FOR EACH ROW EXECUTE FUNCTION factory_exec_job_guard()"
    )
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
      EXECUTE format('REVOKE ALL ON %I.factory_exec_roles,%I.factory_exec_plans,%I.factory_exec_requests,%I.factory_exec_decisions,%I.factory_exec_revocations,%I.factory_exec_jobs FROM caliburn',current_schema(),current_schema(),current_schema(),current_schema(),current_schema(),current_schema());
      EXECUTE format('GRANT SELECT ON %I.factory_exec_roles,%I.factory_exec_plans,%I.factory_exec_requests,%I.factory_exec_decisions,%I.factory_exec_revocations,%I.factory_exec_jobs TO caliburn',current_schema(),current_schema(),current_schema(),current_schema(),current_schema(),current_schema());
      EXECUTE format('GRANT INSERT ON %I.factory_exec_requests,%I.factory_exec_jobs TO caliburn',current_schema(),current_schema());
    END IF; END $$""")
    # Invoker authority must resolve application tables before any caller-owned temp
    # objects. pg_catalog remains implicitly first; explicit pg_temp is always last.
    schema = (
        op.get_bind().exec_driver_sql("SELECT current_schema()").scalar_one().replace('"', '""')
    )
    for function in (
        "reject_runtime_event_mutation",
        "policy_immutable_record",
        "policy_stamp_author",
        "policy_check_reviewer",
        "policy_candidate_parent",
        "factory_immutable",
        "factory_scope",
        "factory_verifier_owner",
        "factory_check_job_guard",
        "factory_check_report_guard",
        "factory_exec_request_guard",
        "factory_exec_reviewer_guard",
        "factory_exec_job_guard",
    ):
        op.execute(f'ALTER FUNCTION "{schema}".{function}() SET search_path TO "{schema}",pg_temp')


def downgrade():
    for name in (
        "factory_exec_jobs",
        "factory_exec_revocations",
        "factory_exec_decisions",
        "factory_exec_requests",
        "factory_exec_plans",
        "factory_exec_roles",
    ):
        op.drop_table(name)
    if op.get_bind().dialect.name == "postgresql":
        for name in (
            "factory_exec_job_guard",
            "factory_exec_reviewer_guard",
            "factory_exec_request_guard",
        ):
            op.execute("DROP FUNCTION " + name + "()")
