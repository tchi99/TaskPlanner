"""TP-026A: one fresh schema root. No legacy data migration or automatic reset.

Revision ID: 0020_tp026_fresh
Revises:
"""
from alembic import op
from sqlalchemy import inspect

from app.infrastructure.db import Base
from app.infrastructure import models  # noqa: F401; register authoritative ORM tables


revision = "0020_tp026_fresh"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    connection = op.get_bind()
    # Alembic itself creates alembic_version. Refuse all other preexisting
    # tables: never stamp, drop, or transform an unidentified/legacy database.
    existing = set(inspect(connection).get_table_names())
    unexpected = existing - {"alembic_version"}
    if unexpected:
        raise RuntimeError(
            "TP-026 requires a fresh empty database; refusing to mutate "
            "existing schema tables: " + ", ".join(sorted(unexpected))
        )
    Base.metadata.create_all(bind=connection, checkfirst=False)


def downgrade() -> None:
    raise RuntimeError(
        "TP-026 fresh baseline is not destructively downgradable; "
        "reset only a separately verified disposable local database"
    )
