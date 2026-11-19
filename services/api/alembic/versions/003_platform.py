"""Remaining tenant-isolated platform tables."""

from app.migration_source import alembic_upgrade

revision = "003_platform"
down_revision = "002_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    alembic_upgrade("003_platform")


def downgrade() -> None:
    raise RuntimeError(
        "Clinical schema downgrade is disabled; use a reviewed recovery migration."
    )
