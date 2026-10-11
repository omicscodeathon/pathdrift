"""Persist run-scoped Phase 3 biological analysis results."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261006_01"
down_revision = "20261005_02"
branch_labels = None
depends_on = None


def _uuid():
    return sa.Column("id", sa.String(36), primary_key=True)


def upgrade() -> None:
    op.create_table(
        "run_differential_expression",
        _uuid(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gene_id", sa.String(36), sa.ForeignKey("genes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("species", sa.String(16), nullable=False),
        sa.Column("comparison", sa.String(100), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("log2fc", sa.Float()),
        sa.Column("pvalue", sa.Float()),
        sa.Column("adjusted_p_value", sa.Float()),
        sa.Column("statistic", sa.Float()),
        sa.Column("base_mean", sa.Float()),
        sa.Column("average_expression", sa.Float()),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("significant", sa.Boolean(), nullable=False),
        sa.Column("thresholds", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "dataset_id", "comparison", "gene_id", name="uq_run_de_comparison_gene"),
    )
    op.create_index("ix_run_de_run_species", "run_differential_expression", ["run_id", "species"])
    op.create_index("ix_run_de_run_comparison", "run_differential_expression", ["run_id", "comparison"])
    op.create_index("ix_run_de_gene", "run_differential_expression", ["gene_id"])
    op.create_index("ix_run_de_adjusted_p", "run_differential_expression", ["adjusted_p_value"])
    op.create_index("ix_run_de_significant", "run_differential_expression", ["significant"])

    op.create_table(
        "run_gene_networks",
        _uuid(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("species", sa.String(16), nullable=False),
        sa.Column("disease_state", sa.String(32), nullable=False),
        sa.Column("method", sa.String(24), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("run_id", "dataset_id", "name", name="uq_run_network_dataset_name"),
    )
    op.create_index("ix_run_networks_run_species", "run_gene_networks", ["run_id", "species"])

    op.create_table(
        "run_network_modules",
        _uuid(),
        sa.Column("network_id", sa.String(36), sa.ForeignKey("run_gene_networks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_key", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("detection_method", sa.String(64), nullable=False),
        sa.Column("parameters", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("network_id", "module_key", name="uq_run_network_module_key"),
    )
    op.create_index("ix_run_modules_network", "run_network_modules", ["network_id"])

    op.create_table(
        "run_network_nodes",
        _uuid(),
        sa.Column("network_id", sa.String(36), sa.ForeignKey("run_gene_networks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gene_id", sa.String(36), sa.ForeignKey("genes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("module_id", sa.String(36), sa.ForeignKey("run_network_modules.id", ondelete="SET NULL")),
        sa.Column("degree", sa.Integer(), nullable=False),
        sa.Column("weighted_degree", sa.Float(), nullable=False),
        sa.Column("betweenness_centrality", sa.Float()),
        sa.Column("closeness_centrality", sa.Float()),
        sa.Column("eigenvector_centrality", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("network_id", "gene_id", name="uq_run_network_node_gene"),
    )
    op.create_index("ix_run_network_nodes_network", "run_network_nodes", ["network_id"])
    op.create_index("ix_run_network_nodes_gene", "run_network_nodes", ["gene_id"])

    op.create_table(
        "run_network_edges",
        _uuid(),
        sa.Column("network_id", sa.String(36), sa.ForeignKey("run_gene_networks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_gene_id", sa.String(36), sa.ForeignKey("genes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("target_gene_id", sa.String(36), sa.ForeignKey("genes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("correlation", sa.Float(), nullable=False),
        sa.Column("absolute_correlation", sa.Float(), nullable=False),
        sa.Column("pvalue", sa.Float(), nullable=False),
        sa.Column("adjusted_p_value", sa.Float(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("network_id", "source_gene_id", "target_gene_id", name="uq_run_network_undirected_edge"),
    )
    op.create_index("ix_run_network_edges_network", "run_network_edges", ["network_id"])
    op.create_index("ix_run_network_edges_source", "run_network_edges", ["source_gene_id"])
    op.create_index("ix_run_network_edges_target", "run_network_edges", ["target_gene_id"])

    op.create_table(
        "run_module_genes",
        _uuid(),
        sa.Column("module_id", sa.String(36), sa.ForeignKey("run_network_modules.id", ondelete="CASCADE"), nullable=False),
        sa.Column("gene_id", sa.String(36), sa.ForeignKey("genes.id", ondelete="CASCADE"), nullable=False),
        sa.Column("membership", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("module_id", "gene_id", name="uq_run_module_gene"),
    )
    op.create_index("ix_run_module_genes_gene", "run_module_genes", ["gene_id"])

    op.create_table(
        "run_figures",
        _uuid(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("dataset_id", sa.String(36), sa.ForeignKey("datasets.id", ondelete="CASCADE")),
        sa.Column("network_id", sa.String(36), sa.ForeignKey("run_gene_networks.id", ondelete="CASCADE")),
        sa.Column("stage", sa.String(32), nullable=False),
        sa.Column("figure_type", sa.String(64), nullable=False),
        sa.Column("file_path", sa.String(1024), nullable=False),
        sa.Column("format", sa.String(12), nullable=False),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_run_figures_run_stage", "run_figures", ["run_id", "stage"])


def downgrade() -> None:
    op.drop_table("run_figures")
    op.drop_table("run_module_genes")
    op.drop_table("run_network_edges")
    op.drop_table("run_network_nodes")
    op.drop_table("run_network_modules")
    op.drop_table("run_gene_networks")
    op.drop_table("run_differential_expression")
