"""Scoped internal releases and durable version-pinned invocation."""

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

revision = "0009_internal_registry"
down_revision = "0008_signed_evidence"
branch_labels = None
depends_on = None
metadata = MetaData()
for name in ("factory_signed_artifacts", "factory_signing_keys", "runtime_tasks", "runtime_steps"):
    Table(
        name,
        metadata,
        Column(
            "id", String(64) if name == "factory_signing_keys" else String(36), primary_key=True
        ),
    )
signed_artifacts = metadata.tables["factory_signed_artifacts"]
signing_keys = metadata.tables["factory_signing_keys"]
# Internal release authority is separate from evidence signing and task clients.
release_reviewers = Table(
    "registry_reviewers",
    metadata,
    Column("db_role", String(63), primary_key=True),
    Column("principal", String(80), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("enabled", String(3), nullable=False),
)
release_executors = Table(
    "registry_executors",
    metadata,
    Column("db_role", String(63), primary_key=True),
    Column("principal", String(80), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("enabled", String(3), nullable=False),
)
release_requests = Table(
    "registry_requests",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("artifact_id", ForeignKey(signed_artifacts.c.id), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("binding", JSON, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("creator_role", String(63), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)
release_decisions = Table(
    "registry_decisions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("request_id", ForeignKey(release_requests.c.id), nullable=False, unique=True),
    Column("reviewer_role", String(63), nullable=False),
    Column("decision", String(10), nullable=False),
    Column("binding_sha256", String(64), nullable=False),
    Column("license_scope", String(30), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
)
release_versions = Table(
    "registry_versions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("request_id", ForeignKey(release_requests.c.id), nullable=False, unique=True),
    Column("artifact_id", ForeignKey(signed_artifacts.c.id), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("name", String(64), nullable=False),
    Column("version", String(40), nullable=False),
    Column("signer_role", String(63), nullable=False),
    Column("key_id", ForeignKey(signing_keys.c.id), nullable=False),
    Column("envelope", JSON, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    UniqueConstraint("actor", "tenant", "name", "version"),
)
release_heads = Table(
    "registry_heads",
    metadata,
    Column("actor", String(100), primary_key=True),
    Column("tenant", String(100), primary_key=True),
    Column("name", String(64), primary_key=True),
    Column("release_id", ForeignKey(release_versions.c.id), nullable=False),
    Column("operator_role", String(63), nullable=False),
    Column("updated_at", Float, nullable=False),
)
release_head_events = Table(
    "registry_head_events",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("name", String(64), nullable=False),
    Column("from_release", String(36)),
    Column("to_release", ForeignKey(release_versions.c.id), nullable=False),
    Column("operator_role", String(63), nullable=False),
    Column("created_at", Float, nullable=False),
)
release_invocations = Table(
    "registry_invocations",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("task_id", ForeignKey("runtime_tasks.id"), nullable=False),
    Column("step_id", ForeignKey("runtime_steps.id"), nullable=False, unique=True),
    Column("release_id", ForeignKey(release_versions.c.id), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("arguments", JSON, nullable=False),
    Column("input_sha256", String(64), nullable=False),
    Column("creator_role", String(63), nullable=False),
    Column("state", String(20), nullable=False),
    Column("attempts", Integer, nullable=False),
    Column("created_at", Float, nullable=False),
    Column("lease_token", String(36)),
    Column("lease_until", Float),
    Column("executor_role", String(63)),
    Column("result", JSON),
    Column("result_sha256", String(64)),
)
release_revocations = Table(
    "registry_revocations",
    metadata,
    Column("release_id", ForeignKey(release_versions.c.id), primary_key=True),
    Column("operator_role", String(63), nullable=False),
    Column("reason", String(40), nullable=False),
    Column("invocation_id", ForeignKey(release_invocations.c.id)),
    Column("created_at", Float, nullable=False),
)

TABLES = [
    release_reviewers,
    release_executors,
    release_requests,
    release_decisions,
    release_versions,
    release_heads,
    release_head_events,
    release_invocations,
    release_revocations,
]


def upgrade():
    metadata.create_all(op.get_bind(), tables=TABLES)
    if op.get_bind().dialect.name != "postgresql":
        return
    for t in ("registry_reviewers", "registry_executors", "registry_requests"):
        op.execute(
            f"CREATE TRIGGER {t}_owner BEFORE INSERT OR UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION factory_verifier_owner()"
        )
    for t in (
        "registry_requests",
        "registry_decisions",
        "registry_versions",
        "registry_revocations",
        "registry_head_events",
    ):
        op.execute(
            f"CREATE TRIGGER {t}_immutable BEFORE UPDATE OR DELETE ON {t} FOR EACH ROW EXECUTE FUNCTION factory_immutable()"
        )
    op.execute("""CREATE FUNCTION registry_decision_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r registry_requests%ROWTYPE; a factory_signed_artifacts%ROWTYPE; j factory_exec_jobs%ROWTYPE;
      x factory_exec_requests%ROWTYPE; p factory_exec_plans%ROWTYPE; b factory_bundles%ROWTYPE; v factory_check_reports%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM registry_requests WHERE id=NEW.request_id;
      SELECT * INTO a FROM factory_signed_artifacts WHERE id=r.artifact_id;
      SELECT * INTO j FROM factory_exec_jobs WHERE id=a.job_id;
      SELECT * INTO x FROM factory_exec_requests WHERE id=j.request_id;
      SELECT * INTO p FROM factory_exec_plans WHERE id=x.plan_id;
      SELECT * INTO b FROM factory_bundles WHERE id=p.bundle_id;
      SELECT * INTO v FROM factory_check_reports WHERE id=p.report_id;
      IF r.id IS NULL OR a.id IS NULL OR j.id IS NULL OR b.id IS NULL
        OR NEW.decision NOT IN ('APPROVE','REJECT') OR NEW.binding_sha256<>r.sha256
        OR r.expires_at<=extract(epoch FROM clock_timestamp()) OR NEW.expires_at>r.expires_at
        OR (NEW.decision='APPROVE' AND NEW.license_scope<>'internal_development')
        OR current_user IN (r.creator_role,a.signer_role,j.executor_role,x.creator_role,p.owner_role,b.creator_role,v.verifier_role)
        OR NOT EXISTS(SELECT 1 FROM registry_reviewers q WHERE q.db_role=current_user AND q.enabled='yes' AND q.tenant=r.tenant AND q.principal<>r.actor)
        OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
      THEN RAISE EXCEPTION 'independent internal release review denied'; END IF;
      NEW.reviewer_role:=current_user; NEW.created_at:=extract(epoch FROM clock_timestamp()); RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION registry_version_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE r registry_requests%ROWTYPE; d registry_decisions%ROWTYPE; k factory_signing_keys%ROWTYPE;
    BEGIN
      SELECT * INTO r FROM registry_requests WHERE id=NEW.request_id;
      SELECT * INTO d FROM registry_decisions WHERE request_id=r.id;
      SELECT * INTO k FROM factory_signing_keys WHERE id=NEW.key_id;
      IF r.id IS NULL OR d.id IS NULL OR k.id IS NULL OR d.decision<>'APPROVE'
        OR d.license_scope<>'internal_development' OR d.binding_sha256<>r.sha256
        OR NEW.artifact_id<>r.artifact_id OR NEW.actor<>r.actor OR NEW.tenant<>r.tenant
        OR NEW.name IS DISTINCT FROM r.binding::jsonb->>'name'
        OR NEW.version IS DISTINCT FROM r.binding::jsonb->>'version'
        OR current_user=d.reviewer_role OR k.signer_role<>current_user OR k.state<>'ACTIVE'
        OR k.tenant<>r.tenant OR k.expires_at<=extract(epoch FROM clock_timestamp())
        OR NEW.expires_at>least(k.expires_at,d.expires_at,r.expires_at) OR NEW.expires_at<=extract(epoch FROM clock_timestamp())
        OR NOT EXISTS(SELECT 1 FROM registry_reviewers q WHERE q.db_role=d.reviewer_role AND q.enabled='yes' AND q.tenant=r.tenant)
        OR NOT EXISTS(SELECT 1 FROM factory_registry_roles q WHERE q.db_role=current_user AND q.enabled='yes' AND q.tenant=r.tenant AND q.principal<>r.actor)
        OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
        OR NEW.envelope::jsonb->>'algorithm' IS DISTINCT FROM 'Ed25519'
        OR NEW.envelope::jsonb->'statement'->>'scope' IS DISTINCT FROM 'internal_development'
        OR NEW.envelope::jsonb->'statement'->>'request_ref' IS DISTINCT FROM r.id
        OR NEW.envelope::jsonb->'statement'->>'binding_sha256' IS DISTINCT FROM r.sha256
        OR NEW.envelope::jsonb->'statement'->>'approval_ref' IS DISTINCT FROM d.id
        OR NEW.envelope::jsonb->'statement'->>'key_id' IS DISTINCT FROM k.id
      THEN RAISE EXCEPTION 'independently approved signed internal release required'; END IF;
      NEW.signer_role:=current_user; NEW.created_at:=extract(epoch FROM clock_timestamp()); RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION registry_head_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE v registry_versions%ROWTYPE; ownername text;
    BEGIN
      SELECT pg_get_userbyid(relowner) INTO ownername FROM pg_class WHERE oid=TG_RELID;
      SELECT * INTO v FROM registry_versions WHERE id=NEW.release_id;
      IF v.id IS NULL OR v.actor<>NEW.actor OR v.tenant<>NEW.tenant OR v.name<>NEW.name
        OR v.expires_at<=extract(epoch FROM clock_timestamp())
        OR EXISTS(SELECT 1 FROM registry_revocations WHERE release_id=v.id)
        OR (current_user<>ownername AND (current_user<>v.signer_role OR
          NOT EXISTS(SELECT 1 FROM factory_registry_roles q WHERE q.db_role=current_user AND q.enabled='yes' AND q.tenant=v.tenant)))
      THEN RAISE EXCEPTION 'internal release head denied'; END IF;
      NEW.operator_role:=current_user; NEW.updated_at:=extract(epoch FROM clock_timestamp()); RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION registry_head_history() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      INSERT INTO registry_head_events(id,actor,tenant,name,from_release,to_release,operator_role,created_at)
      VALUES(md5(random()::text||clock_timestamp()::text),NEW.actor,NEW.tenant,NEW.name,
        CASE WHEN TG_OP='UPDATE' THEN OLD.release_id ELSE NULL END,NEW.release_id,current_user,extract(epoch FROM clock_timestamp()));
      RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION registry_history_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN IF pg_trigger_depth()<>2 THEN RAISE EXCEPTION 'head history is trigger authored'; END IF; RETURN NEW; END $$""")
    op.execute("""CREATE FUNCTION registry_invocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE t runtime_tasks%ROWTYPE; s runtime_steps%ROWTYPE; v registry_versions%ROWTYPE;
    BEGIN
      SELECT * INTO t FROM runtime_tasks WHERE id=NEW.task_id;
      SELECT * INTO s FROM runtime_steps WHERE id=NEW.step_id;
      SELECT * INTO v FROM registry_versions WHERE id=NEW.release_id;
      IF t.id IS NULL OR s.id IS NULL OR v.id IS NULL OR s.task_id<>t.id OR s.kind<>'TOOL'
        OR NEW.tenant<>t.tenant OR v.tenant<>t.tenant OR v.actor<>t.actor
        OR (t.policy::jsonb->'capabilities'->v.name->>'release_id') IS DISTINCT FROM v.id
        OR (s.input::jsonb->'function'->>'name') IS DISTINCT FROM v.name
      THEN RAISE EXCEPTION 'scoped pinned invocation denied'; END IF;
      IF TG_OP='INSERT' THEN
        IF NEW.state<>'QUEUED' OR NEW.attempts<>0 OR NEW.result IS NOT NULL OR NEW.lease_token IS NOT NULL OR NEW.lease_until IS NOT NULL OR NEW.executor_role IS NOT NULL
          OR NOT has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'UPDATE')
        THEN RAISE EXCEPTION 'runtime invocation request required'; END IF;
        NEW.creator_role:=current_user; NEW.created_at:=extract(epoch FROM clock_timestamp());
      ELSE
        IF (to_jsonb(NEW)-ARRAY['state','attempts','lease_token','lease_until','executor_role','result','result_sha256'])
            IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['state','attempts','lease_token','lease_until','executor_role','result','result_sha256'])
          OR OLD.state='COMPLETED' OR NEW.state NOT IN ('RUNNING','COMPLETED')
          OR NOT EXISTS(SELECT 1 FROM registry_executors q WHERE q.db_role=current_user AND q.tenant=t.tenant AND q.enabled='yes')
          OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
          OR NEW.attempts<OLD.attempts OR NEW.attempts>OLD.attempts+1 OR NEW.attempts>least(3,(t.limits::jsonb->>'max_retries')::int+1)
          OR (NEW.state='RUNNING' AND t.state<>'RUNNING')
          OR (NEW.state='RUNNING' AND NEW.lease_until>t.deadline)
          OR (NEW.attempts=OLD.attempts+1 AND (NEW.state<>'RUNNING' OR (OLD.state='RUNNING' AND OLD.lease_until>extract(epoch FROM clock_timestamp())) OR NEW.lease_token IS NOT DISTINCT FROM OLD.lease_token))
          OR (NEW.attempts=OLD.attempts AND NEW.state='RUNNING' AND (OLD.state<>'RUNNING' OR OLD.executor_role<>current_user OR NEW.lease_token IS DISTINCT FROM OLD.lease_token))
          OR (OLD.state='RUNNING' AND OLD.lease_until>extract(epoch FROM clock_timestamp()) AND OLD.executor_role<>current_user)
          OR (NEW.state='COMPLETED' AND NEW.result::jsonb->>'ok'='true' AND (OLD.state<>'RUNNING' OR OLD.executor_role<>current_user OR OLD.lease_until<=extract(epoch FROM clock_timestamp()) OR t.state<>'RUNNING'))
          OR (NEW.state='RUNNING' AND (NEW.lease_token IS NULL OR NEW.lease_until<=extract(epoch FROM clock_timestamp())))
          OR (NEW.state='COMPLETED' AND (NEW.result IS NULL OR NEW.result_sha256 IS NULL OR NEW.lease_token IS NOT NULL
             OR NEW.result::jsonb->>'release_ref' IS DISTINCT FROM v.id
             OR NEW.result::jsonb->>'version' IS DISTINCT FROM v.version
             OR NEW.result::jsonb->>'source_sha256' IS DISTINCT FROM v.envelope::jsonb->'statement'->>'source_sha256'))
        THEN RAISE EXCEPTION 'independent invocation executor required'; END IF;
        NEW.executor_role:=current_user;
      END IF; RETURN NEW;
    END $$""")
    op.execute("""CREATE FUNCTION registry_revocation_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE ownername text; j registry_invocations%ROWTYPE;
    BEGIN
      SELECT pg_get_userbyid(relowner) INTO ownername FROM pg_class WHERE oid=TG_RELID;
      IF current_user<>ownername THEN
        SELECT * INTO j FROM registry_invocations WHERE id=NEW.invocation_id;
        IF j.id IS NULL OR j.release_id<>NEW.release_id OR j.state<>'COMPLETED'
          OR j.executor_role<>current_user OR (j.result::jsonb->>'ok') IS DISTINCT FROM 'false'
          OR NEW.reason NOT IN ('output_schema_failed','execution_failed','platform_secret_denied')
          OR (j.result::jsonb->>'error') IS DISTINCT FROM NEW.reason
          OR NOT EXISTS(SELECT 1 FROM registry_executors q WHERE q.db_role=current_user AND q.tenant=j.tenant AND q.enabled='yes')
        THEN RAISE EXCEPTION 'scoped failed invocation required for quarantine'; END IF;
      END IF;
      NEW.operator_role:=current_user; NEW.created_at:=extract(epoch FROM clock_timestamp()); RETURN NEW;
    END $$""")
    for table, fun in (
        ("registry_decisions", "registry_decision_guard"),
        ("registry_versions", "registry_version_guard"),
        ("registry_heads", "registry_head_guard"),
        ("registry_head_events", "registry_history_guard"),
        ("registry_invocations", "registry_invocation_guard"),
        ("registry_revocations", "registry_revocation_guard"),
    ):
        events = (
            "INSERT OR UPDATE" if table in {"registry_heads", "registry_invocations"} else "INSERT"
        )
        op.execute(
            f"CREATE TRIGGER {table}_author BEFORE {events} ON {table} FOR EACH ROW EXECUTE FUNCTION {fun}()"
        )
    op.execute(
        "CREATE TRIGGER registry_heads_history AFTER INSERT OR UPDATE ON registry_heads FOR EACH ROW EXECUTE FUNCTION registry_head_history()"
    )
    schema = (
        op.get_bind().exec_driver_sql("SELECT current_schema()").scalar_one().replace('"', '""')
    )
    for fun in (
        "registry_decision_guard",
        "registry_version_guard",
        "registry_head_guard",
        "registry_head_history",
        "registry_history_guard",
        "registry_invocation_guard",
        "registry_revocation_guard",
    ):
        op.execute(f'ALTER FUNCTION "{schema}".{fun}() SET search_path TO "{schema}",pg_temp')
    for table in TABLES:
        op.execute(f"""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
          EXECUTE format('REVOKE ALL ON %I.{table.name} FROM caliburn',current_schema());
          EXECUTE format('GRANT SELECT ON %I.{table.name} TO caliburn',current_schema());
        END IF; END $$""")
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
      EXECUTE format('GRANT INSERT ON %I.registry_invocations TO caliburn',current_schema()); END IF; END $$""")


def downgrade():
    for table in reversed(TABLES):
        op.drop_table(table.name)
    if op.get_bind().dialect.name == "postgresql":
        for fun in (
            "registry_decision_guard",
            "registry_version_guard",
            "registry_head_guard",
            "registry_head_history",
            "registry_history_guard",
            "registry_invocation_guard",
            "registry_revocation_guard",
        ):
            op.execute("DROP FUNCTION " + fun + "()")
