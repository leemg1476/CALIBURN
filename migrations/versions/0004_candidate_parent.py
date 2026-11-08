"""Immutable candidate ancestry; additive nullable reference, no automatic reapproval."""

from alembic import op
from sqlalchemy import Column, String

revision = "0004_candidate_parent"
down_revision = "0003_review"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("policy_candidates") as batch:
        batch.add_column(Column("parent_id", String(36), nullable=True))
        batch.create_foreign_key("fk_candidate_parent", "policy_candidates", ["parent_id"], ["id"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("""CREATE FUNCTION policy_candidate_parent() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF NEW.parent_id IS NOT NULL AND NOT EXISTS(SELECT 1 FROM policy_candidates p
            WHERE p.id=NEW.parent_id AND p.task_id=NEW.task_id AND p.workspace_id=NEW.workspace_id
              AND p.actor=NEW.actor AND p.tenant=NEW.tenant)
            THEN RAISE EXCEPTION 'candidate parent scope denied'; END IF;
          RETURN NEW;
        END $$""")
        op.execute(
            "CREATE TRIGGER policy_candidates_parent BEFORE INSERT ON policy_candidates FOR EACH ROW EXECUTE FUNCTION policy_candidate_parent()"
        )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP TRIGGER policy_candidates_parent ON policy_candidates")
        op.execute("DROP FUNCTION policy_candidate_parent()")
    with op.batch_alter_table("policy_candidates") as batch:
        batch.drop_constraint("fk_candidate_parent", type_="foreignkey")
        batch.drop_column("parent_id")
