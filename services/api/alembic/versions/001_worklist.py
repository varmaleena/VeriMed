"""Existing read-only Worklist baseline."""

from app.migration_source import alembic_upgrade

revision = "001_worklist"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    alembic_upgrade("001_worklist")


def downgrade() -> None:
    raise RuntimeError(
        "Clinical schema downgrade is disabled; use a reviewed recovery migration."
    )
