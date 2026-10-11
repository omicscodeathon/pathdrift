"""
Cross-Species Network Drift Comparison Engine

Compares human and mouse network drift after orthology mapping.

Classification per gene:
  CONSERVED    — significant drift in same direction in both species
  HUMAN_SPECIFIC — significant drift in human, not significant in mouse
  MOUSE_SPECIFIC — significant drift in mouse, not significant in human
  DIVERGENT    — significant drift in opposite directions

Conservation Score:
  CS = n_conserved / n_orthologous_genes_with_significant_drift_in_at_least_one_species

All results are traceable to the underlying node_drift DataFrames.
"""
import numpy as np
import pandas as pd
import structlog
from typing import Dict, Tuple
from app.bio.orthology import validate_one_to_one_mappings

logger = structlog.get_logger(__name__)

# Thresholds for "significant" node drift
NODE_DRIFT_THRESHOLD = 0.3    # Node Drift Score above which a gene is considered drifting
DIRECTION_THRESHOLD = 0.0     # degree_change > 0 → increased connectivity
EDGE_REWIRING_THRESHOLD = 0.05


def align_network_edges(
    human_edges: pd.DataFrame,
    mouse_edges: pd.DataFrame,
    orthology_mapping: pd.DataFrame,
) -> Dict[str, float | int | None]:
    """Compare species network edges in a shared human-Ensembl identifier space."""
    required_mapping_columns = {"human_ensembl_id", "mouse_ensembl_id"}
    if not required_mapping_columns.issubset(orthology_mapping.columns):
        raise ValueError("Orthology mapping must contain human and mouse Ensembl IDs")

    mapping = orthology_mapping.dropna(subset=list(required_mapping_columns)).copy()
    if "orthology_type" in mapping.columns:
        mapping = mapping[mapping["orthology_type"] == "ortholog_one2one"]
    mapping = mapping.drop_duplicates(["human_ensembl_id", "mouse_ensembl_id"])
    ambiguous_human = mapping["human_ensembl_id"].duplicated(keep=False)
    ambiguous_mouse = mapping["mouse_ensembl_id"].duplicated(keep=False)
    mapping = mapping.loc[~ambiguous_human & ~ambiguous_mouse]

    human_to_canonical = {
        str(human_id): str(human_id)
        for human_id in mapping["human_ensembl_id"]
    }
    mouse_to_canonical = {
        str(mouse_id): str(human_id)
        for human_id, mouse_id in zip(mapping["human_ensembl_id"], mapping["mouse_ensembl_id"])
    }

    def canonical_edge_weights(edges: pd.DataFrame, id_map: dict[str, str]) -> dict[tuple[str, str], float]:
        if not {"gene1", "gene2"}.issubset(edges.columns):
            return {}
        weight_column = "weight" if "weight" in edges.columns else "correlation" if "correlation" in edges.columns else None
        if weight_column is None:
            return {}

        canonical_weights = {}
        for gene1, gene2, weight in edges[["gene1", "gene2", weight_column]].itertuples(index=False, name=None):
            canonical_gene1 = id_map.get(str(gene1))
            canonical_gene2 = id_map.get(str(gene2))
            if not canonical_gene1 or not canonical_gene2 or canonical_gene1 == canonical_gene2:
                continue
            numeric_weight = pd.to_numeric(weight, errors="coerce")
            if pd.isna(numeric_weight):
                continue
            canonical_weights[tuple(sorted((canonical_gene1, canonical_gene2)))] = abs(float(numeric_weight))
        return canonical_weights

    human_weights = canonical_edge_weights(human_edges, human_to_canonical)
    mouse_weights = canonical_edge_weights(mouse_edges, mouse_to_canonical)
    human_edge_set = set(human_weights)
    mouse_edge_set = set(mouse_weights)
    shared_edges = human_edge_set & mouse_edge_set
    conserved_edges = sum(
        abs(human_weights[edge] - mouse_weights[edge]) < EDGE_REWIRING_THRESHOLD
        for edge in shared_edges
    )
    rewired_edges = len(shared_edges) - conserved_edges
    human_only_edges = len(human_edge_set - mouse_edge_set)
    mouse_only_edges = len(mouse_edge_set - human_edge_set)
    aligned_union = len(human_edge_set | mouse_edge_set)
    preservation = conserved_edges / aligned_union if aligned_union else None

    return {
        "conserved_edges": int(conserved_edges),
        "rewired_edges": int(rewired_edges),
        "human_only_edges": int(human_only_edges),
        "mouse_only_edges": int(mouse_only_edges),
        "human_ortholog_mapped_edges": len(human_edge_set),
        "mouse_ortholog_mapped_edges": len(mouse_edge_set),
        "mapped_ortholog_pairs": len(human_to_canonical),
        "aligned_union_edges": aligned_union,
        "network_preservation": preservation,
        "network_drift": 1.0 - preservation if preservation is not None else None,
    }


def compare_gene_edge_sets(
    gene_id: str,
    normal_edges: pd.DataFrame,
    cancer_edges: pd.DataFrame,
) -> Dict[str, list]:
    """Compare a gene's saved normal and cancer edges and classify relationship changes."""
    def neighbors(edges: pd.DataFrame) -> dict[str, float]:
        if not {"gene1", "gene2"}.issubset(edges.columns):
            return {}
        weight_column = "weight" if "weight" in edges.columns else "correlation" if "correlation" in edges.columns else None
        selected_edges = edges[(edges["gene1"].astype(str) == gene_id) | (edges["gene2"].astype(str) == gene_id)]
        result = {}
        for row in selected_edges.itertuples(index=False):
            left = str(getattr(row, "gene1"))
            right = str(getattr(row, "gene2"))
            neighbor_id = right if left == gene_id else left
            raw_weight = getattr(row, weight_column) if weight_column else 1.0
            numeric_weight = pd.to_numeric(raw_weight, errors="coerce")
            result[neighbor_id] = abs(float(numeric_weight)) if not pd.isna(numeric_weight) else 0.0
        return result

    normal_neighbors = neighbors(normal_edges)
    cancer_neighbors = neighbors(cancer_edges)
    normal_ids = set(normal_neighbors)
    cancer_ids = set(cancer_neighbors)
    lost = normal_ids - cancer_ids
    gained = cancer_ids - normal_ids
    shared = normal_ids & cancer_ids
    rewired = {
        neighbor_id for neighbor_id in shared
        if abs(normal_neighbors[neighbor_id] - cancer_neighbors[neighbor_id]) >= EDGE_REWIRING_THRESHOLD
    }
    drift_types = []
    if lost:
        drift_types.append("Network edge loss")
    if gained:
        drift_types.append("Network edge gain")
    if rewired:
        drift_types.append("Network edge rewiring")
    if not drift_types:
        drift_types.append("No significant edge change")

    return {
        "normal_edges": [
            {"neighbor_id": neighbor_id, "weight": normal_neighbors[neighbor_id]}
            for neighbor_id in sorted(normal_ids, key=lambda item: (-normal_neighbors[item], item))
        ],
        "cancer_edges": [
            {"neighbor_id": neighbor_id, "weight": cancer_neighbors[neighbor_id]}
            for neighbor_id in sorted(cancer_ids, key=lambda item: (-cancer_neighbors[item], item))
        ],
        "lost_relationships": [
            {"neighbor_id": neighbor_id, "normal_weight": normal_neighbors[neighbor_id]}
            for neighbor_id in sorted(lost)
        ],
        "gained_relationships": [
            {"neighbor_id": neighbor_id, "cancer_weight": cancer_neighbors[neighbor_id]}
            for neighbor_id in sorted(gained)
        ],
        "rewired_relationships": [
            {
                "neighbor_id": neighbor_id,
                "normal_weight": normal_neighbors[neighbor_id],
                "cancer_weight": cancer_neighbors[neighbor_id],
            }
            for neighbor_id in sorted(rewired)
        ],
        "drift_types": drift_types,
    }


class CrossSpeciesComparator:
    """
    Compares node-level drift between human and mouse after orthology alignment.

    Parameters
    ----------
    drift_threshold : float
        Minimum node_drift_score to consider a gene as significantly drifting.
    """

    def __init__(self, drift_threshold: float = NODE_DRIFT_THRESHOLD):
        self.drift_threshold = drift_threshold

    def compare(
        self,
        human_node_drift: pd.DataFrame,
        mouse_node_drift: pd.DataFrame,
        orthology_mapping: pd.DataFrame,
    ) -> Dict:
        """
        Compare human and mouse node-level drift using orthology.

        Parameters
        ----------
        human_node_drift : pd.DataFrame
            Output of DriftDetector for human (gene_id indexed by human Ensembl ID).
        mouse_node_drift : pd.DataFrame
            Output of DriftDetector for mouse (gene_id indexed by mouse Ensembl ID).
        orthology_mapping : pd.DataFrame
            Mapping with columns: human_ensembl_id, mouse_ensembl_id, human_symbol, mouse_symbol.

        Returns
        -------
        dict with keys:
            'comparison_df'     : pd.DataFrame (per-gene classification)
            'summary'           : dict
            'conservation_score': float
        """
        h = human_node_drift.set_index("gene_id") if "gene_id" in human_node_drift.columns else human_node_drift
        m = mouse_node_drift.set_index("gene_id") if "gene_id" in mouse_node_drift.columns else mouse_node_drift

        # Map mouse gene IDs to human IDs using orthology
        mapping = validate_one_to_one_mappings(orthology_mapping)

        # Restrict to genes present in both drift result sets
        mapping = mapping[
            mapping["human_ensembl_id"].isin(h.index)
            & mapping["mouse_ensembl_id"].isin(m.index)
        ]

        if mapping.empty:
            raise ValueError(
                "No overlapping orthologous genes found in both drift result sets. "
                "Check that drift analyses used the same gene identifier scheme."
            )

        rows = []
        for _, orth_row in mapping.iterrows():
            h_id = orth_row["human_ensembl_id"]
            m_id = orth_row["mouse_ensembl_id"]

            h_score = h.loc[h_id, "node_drift_score"] if h_id in h.index else 0.0
            m_score = m.loc[m_id, "node_drift_score"] if m_id in m.index else 0.0

            h_significant = h_score >= self.drift_threshold
            m_significant = m_score >= self.drift_threshold

            # Direction: positive degree_change = connectivity gained
            h_dir = np.sign(h.loc[h_id, "degree_change"]) if h_id in h.index else 0
            m_dir = np.sign(m.loc[m_id, "degree_change"]) if m_id in m.index else 0

            # Classify
            if h_significant and m_significant:
                if h_dir == m_dir:
                    classification = "conserved"
                else:
                    classification = "divergent"
            elif h_significant and not m_significant:
                classification = "human_specific"
            elif not h_significant and m_significant:
                classification = "mouse_specific"
            else:
                classification = "not_drifting"

            rows.append(
                {
                    "human_ensembl_id": h_id,
                    "mouse_ensembl_id": m_id,
                    "human_symbol": orth_row.get("human_symbol"),
                    "mouse_symbol": orth_row.get("mouse_symbol"),
                    "orthology_type": orth_row.get("orthology_type"),
                    "ensembl_release": orth_row.get("ensembl_release"),
                    "human_drift_score": h_score,
                    "mouse_drift_score": m_score,
                    "human_degree_change": h.loc[h_id, "degree_change"] if h_id in h.index else 0.0,
                    "mouse_degree_change": m.loc[m_id, "degree_change"] if m_id in m.index else 0.0,
                    "human_significant": h_significant,
                    "mouse_significant": m_significant,
                    "drift_classification": classification,
                }
            )

        comparison_df = pd.DataFrame(rows)

        # Summary statistics
        n_total = len(comparison_df)
        n_conserved = int((comparison_df["drift_classification"] == "conserved").sum())
        n_human_specific = int((comparison_df["drift_classification"] == "human_specific").sum())
        n_mouse_specific = int((comparison_df["drift_classification"] == "mouse_specific").sum())
        n_divergent = int((comparison_df["drift_classification"] == "divergent").sum())
        n_drifting = n_conserved + n_human_specific + n_mouse_specific + n_divergent

        # Conservation Score: fraction of significantly drifting genes that are conserved
        conservation_score = n_conserved / n_drifting if n_drifting > 0 else 0.0

        summary = {
            "n_orthologous_genes": n_total,
            "orthology_mapping_type": "ortholog_one2one",
            "ensembl_releases": sorted(mapping["ensembl_release"].dropna().astype(int).unique().tolist())
            if "ensembl_release" in mapping.columns else [],
            "n_not_drifting": int((comparison_df["drift_classification"] == "not_drifting").sum()),
            "n_conserved": n_conserved,
            "n_human_specific": n_human_specific,
            "n_mouse_specific": n_mouse_specific,
            "n_divergent": n_divergent,
            "conservation_score": conservation_score,
            "drift_threshold_used": self.drift_threshold,
            "score_interpretation": (
                "Conservation score = n_conserved_drift / n_total_significantly_drifting. "
                "Range [0, 1]. Higher = more cross-species conserved network changes."
            ),
        }

        logger.info("cross_species_comparison_done", **{k: v for k, v in summary.items() if isinstance(v, (int, float))})

        return {
            "comparison_df": comparison_df,
            "summary": summary,
            "conservation_score": conservation_score,
        }
