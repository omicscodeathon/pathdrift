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

logger = structlog.get_logger(__name__)

# Thresholds for "significant" node drift
NODE_DRIFT_THRESHOLD = 0.3    # Node Drift Score above which a gene is considered drifting
DIRECTION_THRESHOLD = 0.0     # degree_change > 0 → increased connectivity


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
        mapping = orthology_mapping.copy()

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
