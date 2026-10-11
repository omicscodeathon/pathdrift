"""Persist run-scoped Phase 4 orthology and cross-species network drift."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20261006_02"
down_revision = "20261006_01"
branch_labels = None
depends_on = None


def _id() -> sa.Column:
    return sa.Column("id", sa.String(36), primary_key=True)


def _created_at() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _has_table(name: str) -> bool:
    return name in sa.inspect(op.get_bind()).get_table_names()


def _has_column(table_name: str, column_name: str) -> bool:
    if not _has_table(table_name):
        return False
    return column_name in {
        column["name"] for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _create_table_if_missing(name: str, *columns) -> None:
    if not _has_table(name):
        op.create_table(name, *columns)


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    indexes = {index["name"] for index in sa.inspect(op.get_bind()).get_indexes(table_name)}
    if name not in indexes:
        op.create_index(name, table_name, columns)


def upgrade() -> None:
    if not _has_column("orthology_mappings", "source"):
        op.add_column("orthology_mappings", sa.Column("source", sa.String(100)))
    if not _has_column("orthology_mappings", "source_metadata"):
        op.add_column(
            "orthology_mappings",
            sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text())),
        )
    constraint_names = {
        constraint["name"]
        for constraint in sa.inspect(op.get_bind()).get_unique_constraints("orthology_mappings")
    }
    if "uq_orthology_pair" in constraint_names:
        op.drop_constraint("uq_orthology_pair", "orthology_mappings", type_="unique")
    if "uq_orthology_source_pair_version" not in constraint_names:
        op.create_unique_constraint(
            "uq_orthology_source_pair_version",
            "orthology_mappings",
            ["human_ensembl_id", "mouse_ensembl_id", "source", "source_version"],
        )
    _create_index_if_missing("ix_orthology_source_version", "orthology_mappings", ["source", "source_version"])

    _create_table_if_missing(
        "run_phase4_summaries",
        _id(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("configuration", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("provenance", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        _created_at(),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    _create_index_if_missing("ix_run_phase4_status", "run_phase4_summaries", ["status"])

    _create_table_if_missing(
        "run_orthology_mappings",
        _id(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("human_ensembl_id", sa.String(50), nullable=False),
        sa.Column("mouse_ensembl_id", sa.String(50), nullable=False),
        sa.Column("human_original_id", sa.String(64)),
        sa.Column("mouse_original_id", sa.String(64)),
        sa.Column("human_symbol", sa.String(100)),
        sa.Column("mouse_symbol", sa.String(100)),
        sa.Column("orthology_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("source", sa.String(100), nullable=False),
        sa.Column("source_version", sa.String(100), nullable=False),
        sa.Column("source_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        _created_at(),
        sa.UniqueConstraint("run_id", "human_ensembl_id", "mouse_ensembl_id", "source_version", name="uq_run_orthology_pair_version"),
    )
    _create_index_if_missing("ix_run_orthology_run_human", "run_orthology_mappings", ["run_id", "human_ensembl_id"])
    _create_index_if_missing("ix_run_orthology_run_mouse", "run_orthology_mappings", ["run_id", "mouse_ensembl_id"])
    _create_index_if_missing("ix_run_orthology_type", "run_orthology_mappings", ["run_id", "orthology_type"])

    _create_table_if_missing(
        "run_cross_species_node_alignments",
        _id(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("human_ensembl_id", sa.String(50), nullable=False),
        sa.Column("mouse_ensembl_id", sa.String(50), nullable=False),
        sa.Column("human_symbol", sa.String(100)),
        sa.Column("mouse_symbol", sa.String(100)),
        sa.Column("orthology_type", sa.String(50), nullable=False),
        sa.Column("confidence", sa.Float()),
        sa.Column("human_network_present", sa.Boolean(), nullable=False),
        sa.Column("mouse_network_present", sa.Boolean(), nullable=False),
        sa.Column("is_primary", sa.Boolean(), nullable=False),
        _created_at(),
        sa.UniqueConstraint("run_id", "human_ensembl_id", "mouse_ensembl_id", name="uq_run_cross_species_node_pair"),
    )
    _create_index_if_missing("ix_run_cross_species_nodes_run", "run_cross_species_node_alignments", ["run_id"])

    _create_table_if_missing(
        "run_network_edge_drift",
        _id(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("human_edge_id", sa.String(36), sa.ForeignKey("run_network_edges.id", ondelete="SET NULL")),
        sa.Column("mouse_edge_id", sa.String(36), sa.ForeignKey("run_network_edges.id", ondelete="SET NULL")),
        sa.Column("human_source_gene_id", sa.String(50)),
        sa.Column("human_target_gene_id", sa.String(50)),
        sa.Column("mouse_source_gene_id", sa.String(50)),
        sa.Column("mouse_target_gene_id", sa.String(50)),
        sa.Column("human_weight", sa.Float()),
        sa.Column("mouse_weight", sa.Float()),
        sa.Column("human_p_value", sa.Float()),
        sa.Column("mouse_p_value", sa.Float()),
        sa.Column("human_adjusted_p_value", sa.Float()),
        sa.Column("mouse_adjusted_p_value", sa.Float()),
        sa.Column("weight_difference", sa.Float()),
        sa.Column("absolute_weight_difference", sa.Float()),
        sa.Column("relative_weight_change", sa.Float()),
        sa.Column("status", sa.String(32), nullable=False),
        _created_at(),
    )
    _create_index_if_missing("ix_run_network_edge_drift_run_status", "run_network_edge_drift", ["run_id", "status"])
    _create_index_if_missing("ix_run_network_edge_drift_run_human", "run_network_edge_drift", ["run_id", "human_source_gene_id"])
    _create_index_if_missing("ix_run_network_edge_drift_run_mouse", "run_network_edge_drift", ["run_id", "mouse_source_gene_id"])

    _create_table_if_missing(
        "run_gene_drift",
        _id(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("human_ensembl_id", sa.String(50), nullable=False),
        sa.Column("mouse_ensembl_id", sa.String(50), nullable=False),
        sa.Column("human_symbol", sa.String(100)),
        sa.Column("mouse_symbol", sa.String(100)),
        sa.Column("human_degree", sa.Integer(), nullable=False),
        sa.Column("mouse_degree", sa.Integer(), nullable=False),
        sa.Column("degree_difference", sa.Integer(), nullable=False),
        sa.Column("human_neighbor_count", sa.Integer(), nullable=False),
        sa.Column("mouse_neighbor_count", sa.Integer(), nullable=False),
        sa.Column("conserved_neighbor_count", sa.Integer(), nullable=False),
        sa.Column("lost_neighbor_count", sa.Integer(), nullable=False),
        sa.Column("gained_neighbor_count", sa.Integer(), nullable=False),
        sa.Column("neighbor_similarity", sa.Float(), nullable=False),
        sa.Column("edge_loss_rate", sa.Float(), nullable=False),
        sa.Column("normalized_degree_difference", sa.Float(), nullable=False),
        sa.Column("module_conservation", sa.Float()),
        sa.Column("drift_score", sa.Float(), nullable=False),
        sa.Column("drift_category", sa.String(24), nullable=False),
        _created_at(),
        sa.UniqueConstraint("run_id", "human_ensembl_id", "mouse_ensembl_id", name="uq_run_gene_drift_pair"),
    )
    _create_index_if_missing("ix_run_gene_drift_run_score", "run_gene_drift", ["run_id", "drift_score"])
    _create_index_if_missing("ix_run_gene_drift_run_category", "run_gene_drift", ["run_id", "drift_category"])

    _create_table_if_missing(
        "run_module_drift",
        _id(),
        sa.Column("run_id", sa.String(36), sa.ForeignKey("analysis_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("human_module_id", sa.String(36), nullable=False),
        sa.Column("candidate_mouse_module_id", sa.String(36)),
        sa.Column("human_module_size", sa.Integer(), nullable=False),
        sa.Column("mapped_gene_count", sa.Integer(), nullable=False),
        sa.Column("mouse_module_overlap", sa.Integer(), nullable=False),
        sa.Column("overlap_fraction", sa.Float(), nullable=False),
        sa.Column("module_conservation_score", sa.Float(), nullable=False),
        sa.Column("internal_edge_conservation", sa.Float()),
        sa.Column("classification", sa.String(32), nullable=False),
        _created_at(),
    )
    _create_index_if_missing("ix_run_module_drift_run_human", "run_module_drift", ["run_id", "human_module_id"])
    _create_index_if_missing("ix_run_module_drift_run_class", "run_module_drift", ["run_id", "classification"])


def downgrade() -> None:
    op.drop_table("run_module_drift")
    op.drop_table("run_gene_drift")
    op.drop_table("run_network_edge_drift")
    op.drop_table("run_cross_species_node_alignments")
    op.drop_table("run_orthology_mappings")
    op.drop_table("run_phase4_summaries")
    op.drop_index("ix_orthology_source_version", table_name="orthology_mappings")
    op.drop_constraint("uq_orthology_source_pair_version", "orthology_mappings", type_="unique")
    op.create_unique_constraint(
        "uq_orthology_pair",
        "orthology_mappings",
        ["human_ensembl_id", "mouse_ensembl_id"],
    )
    op.drop_column("orthology_mappings", "source_metadata")
    op.drop_column("orthology_mappings", "source")
