"""Persist acquisition availability on datasets."""
from alembic import op


revision = "20261005_02"
down_revision = "20261005_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE datasets ADD COLUMN IF NOT EXISTS status VARCHAR(32) NOT NULL DEFAULT 'PENDING'")


def downgrade() -> None:
    op.execute("ALTER TABLE datasets DROP COLUMN IF EXISTS status")