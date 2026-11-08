"""Independent Ed25519 evidence registry; no production activation state."""

from alembic import op
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

revision = "0008_signed_evidence"
down_revision = "0007_factory_execution"
branch_labels = None
depends_on = None
metadata = MetaData()
for name in ("factory_bundles", "factory_exec_jobs"):
    Table(name, metadata, Column("id", String(36), primary_key=True))
bundles = metadata.tables["factory_bundles"]
exec_jobs = metadata.tables["factory_exec_jobs"]
registry_roles = Table(
    "factory_registry_roles",
    metadata,
    Column("db_role", String(63), primary_key=True),
    Column("principal", String(80), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("enabled", String(3), nullable=False),
)
signing_keys = Table(
    "factory_signing_keys",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("tenant", String(100), nullable=False),
    Column("signer_role", String(63), nullable=False),
    Column("public_key_hex", String(64), nullable=False),
    Column("not_before", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    Column("state", String(10), nullable=False),
)
signed_artifacts = Table(
    "factory_signed_artifacts",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("bundle_id", ForeignKey(bundles.c.id), nullable=False),
    Column("job_id", ForeignKey(exec_jobs.c.id), nullable=False),
    Column("key_id", ForeignKey(signing_keys.c.id), nullable=False),
    Column("actor", String(100), nullable=False),
    Column("tenant", String(100), nullable=False),
    Column("signer_role", String(63), nullable=False),
    Column("stage", String(20), nullable=False),
    Column("envelope", JSON, nullable=False),
    Column("sha256", String(64), nullable=False),
    Column("created_at", Float, nullable=False),
    Column("expires_at", Float, nullable=False),
    UniqueConstraint("job_id", "key_id"),
    CheckConstraint("stage='EVIDENCE_ONLY'", name="ck_factory_signed_evidence_only"),
)


def upgrade():
    metadata.create_all(op.get_bind(), tables=[registry_roles, signing_keys, signed_artifacts])
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "CREATE TRIGGER factory_registry_roles_owner BEFORE INSERT OR UPDATE OR DELETE ON factory_registry_roles FOR EACH ROW EXECUTE FUNCTION factory_verifier_owner()"
    )
    op.execute(
        "CREATE TRIGGER factory_signing_keys_owner BEFORE INSERT OR UPDATE OR DELETE ON factory_signing_keys FOR EACH ROW EXECUTE FUNCTION factory_verifier_owner()"
    )
    op.execute("""CREATE FUNCTION factory_signing_key_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    BEGIN
      IF TG_OP='UPDATE' AND ((to_jsonb(NEW)-'state') IS DISTINCT FROM (to_jsonb(OLD)-'state')
        OR OLD.state<>'ACTIVE' OR NEW.state<>'REVOKED') THEN
        RAISE EXCEPTION 'immutable public key trust'; END IF;
      IF NEW.state NOT IN ('ACTIVE','REVOKED') OR NEW.expires_at<=NEW.not_before
        OR NEW.public_key_hex !~ '^[0-9a-f]{64}$' THEN
        RAISE EXCEPTION 'invalid public key trust'; END IF;
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_signing_key_guard BEFORE INSERT OR UPDATE ON factory_signing_keys FOR EACH ROW EXECUTE FUNCTION factory_signing_key_guard()"
    )
    op.execute("""CREATE FUNCTION factory_signed_artifact_guard() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE b factory_bundles%ROWTYPE; j factory_exec_jobs%ROWTYPE; r factory_exec_requests%ROWTYPE;
      p factory_exec_plans%ROWTYPE; s factory_check_reports%ROWTYPE; d factory_exec_decisions%ROWTYPE; k factory_signing_keys%ROWTYPE;
    BEGIN
      SELECT * INTO b FROM factory_bundles WHERE id=NEW.bundle_id;
      SELECT * INTO j FROM factory_exec_jobs WHERE id=NEW.job_id;
      SELECT * INTO r FROM factory_exec_requests WHERE id=j.request_id;
      SELECT * INTO p FROM factory_exec_plans WHERE id=r.plan_id;
      SELECT * INTO s FROM factory_check_reports WHERE id=p.report_id;
      SELECT * INTO d FROM factory_exec_decisions WHERE request_id=r.id;
      SELECT * INTO k FROM factory_signing_keys WHERE id=NEW.key_id;
      IF b.id IS NULL OR j.id IS NULL OR r.id IS NULL OR p.id IS NULL OR s.id IS NULL OR d.id IS NULL OR k.id IS NULL
        OR j.state<>'COMPLETED' OR j.executor_role IS NULL OR j.result::jsonb->>'ok' IS DISTINCT FROM 'true'
        OR (j.result::jsonb->'data'->'run'->>'status') IS DISTINCT FROM 'PASSED'
        OR d.decision<>'APPROVE' OR p.bundle_id<>b.id OR NEW.actor<>b.actor OR NEW.tenant<>b.tenant
        OR k.tenant<>b.tenant OR k.signer_role<>current_user OR k.state<>'ACTIVE'
        OR NOT (k.not_before<=extract(epoch FROM clock_timestamp()) AND k.expires_at>extract(epoch FROM clock_timestamp()))
        OR NEW.expires_at>k.expires_at OR NEW.expires_at<=extract(epoch FROM clock_timestamp())
        OR current_user IN (b.creator_role,j.creator_role,r.creator_role,p.owner_role,s.verifier_role,d.reviewer_role,j.executor_role)
        OR NOT EXISTS(SELECT 1 FROM factory_registry_roles a WHERE a.db_role=current_user AND a.enabled='yes' AND a.tenant=b.tenant AND a.principal<>b.actor)
        OR has_table_privilege(current_user,format('%I.runtime_tasks',current_schema()),'INSERT,UPDATE,DELETE')
        OR has_table_privilege(current_user,format('%I.factory_bundles',current_schema()),'INSERT,UPDATE,DELETE')
        OR NEW.stage<>'EVIDENCE_ONLY'
        OR (NEW.envelope::jsonb->>'algorithm') IS DISTINCT FROM 'Ed25519'
        OR (NEW.envelope::jsonb->'statement'->>'purpose') IS DISTINCT FROM 'EVIDENCE_ONLY'
        OR (NEW.envelope::jsonb->'statement'->>'production_approved') IS DISTINCT FROM 'false'
        OR (NEW.envelope::jsonb->'statement'->>'key_id') IS DISTINCT FROM k.id
        OR (NEW.envelope::jsonb->'statement'->>'signer_role') IS DISTINCT FROM current_user
        OR (NEW.envelope::jsonb->'statement'->>'actor') IS DISTINCT FROM b.actor
        OR (NEW.envelope::jsonb->'statement'->>'tenant') IS DISTINCT FROM b.tenant
        OR (NEW.envelope::jsonb->'statement'->>'bundle_ref') IS DISTINCT FROM b.id
        OR (NEW.envelope::jsonb->'statement'->>'execution_job_ref') IS DISTINCT FROM j.id
        OR (NEW.envelope::jsonb->'statement'->>'execution_result_sha256') IS DISTINCT FROM j.result_sha256
        OR NOT coalesce((NEW.envelope::jsonb->>'signature_hex') ~ '^[0-9a-f]{128}$',false)
        OR EXISTS(SELECT 1 FROM factory_exec_revocations v WHERE v.request_id=r.id) THEN
        RAISE EXCEPTION 'independent signed evidence admission denied'; END IF;
      NEW.signer_role:=current_user;
      NEW.created_at:=extract(epoch FROM clock_timestamp());
      RETURN NEW;
    END $$""")
    op.execute(
        "CREATE TRIGGER factory_signed_artifacts_author BEFORE INSERT ON factory_signed_artifacts FOR EACH ROW EXECUTE FUNCTION factory_signed_artifact_guard()"
    )
    op.execute(
        "CREATE TRIGGER factory_signed_artifacts_immutable BEFORE UPDATE OR DELETE ON factory_signed_artifacts FOR EACH ROW EXECUTE FUNCTION factory_immutable()"
    )
    schema = (
        op.get_bind().exec_driver_sql("SELECT current_schema()").scalar_one().replace('"', '""')
    )
    for name in ("factory_signing_key_guard", "factory_signed_artifact_guard"):
        op.execute(f'ALTER FUNCTION "{schema}".{name}() SET search_path TO "{schema}",pg_temp')
    op.execute("""DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
      EXECUTE format('REVOKE ALL ON %I.factory_registry_roles,%I.factory_signing_keys,%I.factory_signed_artifacts FROM caliburn',current_schema(),current_schema(),current_schema());
      EXECUTE format('GRANT SELECT ON %I.factory_registry_roles,%I.factory_signing_keys,%I.factory_signed_artifacts TO caliburn',current_schema(),current_schema(),current_schema());
    END IF; END $$""")


def downgrade():
    for name in ("factory_signed_artifacts", "factory_signing_keys", "factory_registry_roles"):
        op.drop_table(name)
    if op.get_bind().dialect.name == "postgresql":
        for name in ("factory_signed_artifact_guard", "factory_signing_key_guard"):
            op.execute("DROP FUNCTION " + name + "()")
