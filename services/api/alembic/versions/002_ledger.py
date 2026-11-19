"""Existing append-only ledger baseline."""

from app.migration_source import alembic_upgrade

revision = "002_ledger"
down_revision = "001_worklist"
branch_labels = None
depends_on = None


def upgrade() -> None:
    alembic_upgrade("002_ledger")


def downgrade() -> None:
    raise RuntimeError("Ledger history must not be removed by schema downgrade.")
