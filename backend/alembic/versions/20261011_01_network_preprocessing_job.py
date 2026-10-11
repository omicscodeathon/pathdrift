"""Associate network results with their preprocessing job."""
from alembic import op
import sqlalchemy as sa


revision = "20261011_01"
down_revision = "20261006_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gene_networks",
        sa.Column("preprocessing_job_id", sa.String(36), nullable=True),
    )
    op.create_foreign_key(
        "fk_gene_networks_preprocessing_job_id",
        "gene_networks",
        "preprocessing_jobs",
        ["preprocessing_job_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_gene_networks_preprocessing_job_id",
        "gene_networks",
        type_="foreignkey",
    )
    op.drop_column("gene_networks", "preprocessing_job_id")
