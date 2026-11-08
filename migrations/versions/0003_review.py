"""Immutable candidate/review records and separated PostgreSQL review authority."""

from alembic import op

revision = "0003_review"
down_revision = "0002_workspace"
branch_labels = None
depends_on = None

from sqlalchemy import JSON, Column, Float, ForeignKey, MetaData, String, Table, UniqueConstraint

metadata = MetaData()
for existing in ("runtime_tasks", "runtime_steps", "sandbox_workspaces"):
    Table(existing, metadata, Column("id", String(36), primary_key=True))

candidates = Table(
    "policy_candidates",
    metadata,
    Column("id", String(36), primary_key=True),
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


def upgrade():
    metadata.create_all(
        op.get_bind(), tables=[t for t in metadata.sorted_tables if t.name.startswith("policy_")]
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION policy_immutable_record() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN RAISE EXCEPTION 'policy records are immutable'; END $$""")
        for table in (
            "policy_candidates",
            "policy_test_plans",
            "policy_review_requests",
            "policy_review_decisions",
            "policy_review_revocations",
        ):
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION policy_immutable_record()"
            )
        op.execute("""CREATE FUNCTION policy_stamp_author() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE t record;
        BEGIN
          NEW.creator_role := current_user;
          SELECT * INTO t FROM runtime_tasks WHERE id=NEW.task_id;
          IF NOT FOUND THEN RAISE EXCEPTION 'task required'; END IF;
          IF TG_TABLE_NAME='policy_candidates' THEN
            IF NEW.workspace_id IS DISTINCT FROM t.workspace_ref OR NOT EXISTS
              (SELECT 1 FROM runtime_steps WHERE id=NEW.step_id AND task_id=t.id)
              THEN RAISE EXCEPTION 'candidate scope mismatch'; END IF;
            NEW.actor := t.actor; NEW.tenant := t.tenant;
          END IF;
          RETURN NEW;
        END $$""")
        for table in ("policy_candidates", "policy_review_requests"):
            op.execute(
                f"CREATE TRIGGER {table}_author BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION policy_stamp_author()"
            )
        op.execute("""CREATE FUNCTION policy_check_reviewer() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE r record; cand record; t record; reviewer record; now_epoch double precision;
        BEGIN
          now_epoch := extract(epoch FROM clock_timestamp());
          SELECT * INTO r FROM policy_review_requests WHERE id=NEW.request_id;
          IF NOT FOUND THEN RAISE EXCEPTION 'request required'; END IF;
          SELECT * INTO cand FROM policy_candidates WHERE id=r.candidate_id;
          SELECT * INTO t FROM runtime_tasks WHERE id=r.task_id;
          SELECT * INTO reviewer FROM policy_reviewers WHERE db_role=current_user AND tenant=t.tenant AND enabled='yes';
          IF NOT FOUND OR current_user=r.creator_role OR current_user=cand.creator_role OR reviewer.principal=t.actor
            THEN RAISE EXCEPTION 'independent reviewer required'; END IF;
          NEW.reviewer_role := current_user; NEW.created_at := now_epoch;
          IF TG_TABLE_NAME='policy_review_decisions' THEN
            IF t.state<>'WAITING_APPROVAL' OR r.expires_at<=now_epoch OR t.deadline<=now_epoch
              OR NEW.binding_digest IS DISTINCT FROM r.digest OR NEW.decision NOT IN ('APPROVE','REJECT')
              OR NEW.expires_at<=now_epoch OR NEW.expires_at>least(r.expires_at,now_epoch+3600)
              THEN RAISE EXCEPTION 'review binding/state/expiry denied'; END IF;
          ELSIF NOT EXISTS(SELECT 1 FROM policy_review_decisions WHERE request_id=r.id) THEN
            RAISE EXCEPTION 'decision required before revoke';
          END IF;
          RETURN NEW;
        END $$""")
        for table in ("policy_review_decisions", "policy_review_revocations"):
            op.execute(
                f"CREATE TRIGGER {table}_authority BEFORE INSERT ON {table} FOR EACH ROW EXECUTE FUNCTION policy_check_reviewer()"
            )
        op.execute("""DO $$ BEGIN
        IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='caliburn') THEN
          EXECUTE format('REVOKE INSERT,UPDATE,DELETE ON %I.policy_reviewers,%I.policy_test_plans,%I.policy_review_decisions,%I.policy_review_revocations FROM caliburn',current_schema(),current_schema(),current_schema(),current_schema());
          EXECUTE format('GRANT SELECT ON %I.policy_reviewers,%I.policy_test_plans,%I.policy_review_decisions,%I.policy_review_revocations TO caliburn',current_schema(),current_schema(),current_schema(),current_schema());
          EXECUTE format('REVOKE UPDATE,DELETE ON %I.policy_candidates,%I.policy_review_requests FROM caliburn',current_schema(),current_schema());
        END IF; END $$""")


def downgrade():
    for name in (
        "policy_review_revocations",
        "policy_review_decisions",
        "policy_review_requests",
        "policy_reviewers",
        "policy_test_plans",
        "policy_candidates",
    ):
        op.drop_table(name)
    if op.get_bind().dialect.name == "postgresql":
        for name in ("policy_check_reviewer", "policy_stamp_author", "policy_immutable_record"):
            op.execute("DROP FUNCTION " + name + "()")
