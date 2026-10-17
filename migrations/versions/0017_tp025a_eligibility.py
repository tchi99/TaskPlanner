"""TP-025A opt-in eligibility storage; no legacy rewrite or feature activation.

Revision ID: 0017_tp025a
Revises: 0016_tp024a
"""
from alembic import op
import sqlalchemy as sa

revision = "0017_tp025a"
down_revision = "0016_tp024a"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "eligibility_series",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("scope_id", sa.String(36), sa.ForeignKey(
            "schedule_scopes.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("work_type_id", sa.String(36), sa.ForeignKey(
            "work_types.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version > 0", name="ck_eligibility_series_version"),
    )
    op.create_index("ix_eligibility_series_owner", "eligibility_series", ["owner_id"])
    op.create_table(
        "eligibility_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("series_id", sa.String(36), sa.ForeignKey(
            "eligibility_series.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("timezone_name", sa.String(100), nullable=False),
        sa.Column("days_of_week", sa.JSON(), nullable=False),
        sa.Column("starts_at_local", sa.String(5), nullable=False),
        sa.Column("ends_at_local", sa.String(5), nullable=False),
        sa.Column("priority_rank", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("start_fold", sa.Integer(), nullable=True),
        sa.Column("end_fold", sa.Integer(), nullable=True),
        sa.Column("supersedes_future", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("series_id", "number", name="uq_eligibility_revision_number"),
        sa.CheckConstraint("number > 0", name="ck_eligibility_revision_number"),
        sa.CheckConstraint("priority_rank IS NULL OR priority_rank > 0",
                           name="ck_eligibility_priority_rank"),
        sa.CheckConstraint("start_fold IS NULL OR start_fold IN (0,1)",
                           name="ck_eligibility_start_fold"),
        sa.CheckConstraint("end_fold IS NULL OR end_fold IN (0,1)",
                           name="ck_eligibility_end_fold"),
        sa.CheckConstraint("valid_until IS NULL OR valid_until > effective_from",
                           name="ck_eligibility_revision_range"),
    )
    op.create_index("ix_eligibility_revision_dates", "eligibility_revisions",
                    ["series_id", "effective_from", "number"])
    op.create_table(
        "eligibility_exceptions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("series_id", sa.String(36), sa.ForeignKey(
            "eligibility_series.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("original_local_date", sa.Date(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_id", "series_id", "original_local_date",
                            name="uq_eligibility_exception_target"),
        sa.CheckConstraint("version > 0", name="ck_eligibility_exception_version"),
    )
    op.create_index("ix_eligibility_exceptions_owner", "eligibility_exceptions",
                    ["owner_id", "series_id"])
    op.create_table(
        "eligibility_exception_revisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("exception_id", sa.String(36), sa.ForeignKey(
            "eligibility_exceptions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(16), nullable=False),
        sa.Column("timezone_name", sa.String(100), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("exception_id", "number",
                            name="uq_eligibility_exception_revision"),
        sa.CheckConstraint("number > 0", name="ck_eligibility_exception_rev_number"),
        sa.CheckConstraint("action IN ('REMOVE','MOVE')",
                           name="ck_eligibility_exception_action"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in ("eligibility_exception_revisions", "eligibility_exceptions",
                  "eligibility_revisions", "eligibility_series"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("cannot downgrade: eligibility history must be retained")
    op.drop_table("eligibility_exception_revisions")
    op.drop_index("ix_eligibility_exceptions_owner", table_name="eligibility_exceptions")
    op.drop_table("eligibility_exceptions")
    op.drop_index("ix_eligibility_revision_dates", table_name="eligibility_revisions")
    op.drop_table("eligibility_revisions")
    op.drop_index("ix_eligibility_series_owner", table_name="eligibility_series")
    op.drop_table("eligibility_series")
