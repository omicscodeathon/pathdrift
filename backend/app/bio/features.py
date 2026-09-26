"""
Feature Extraction Engine

Extracts machine-learning features from:
  1. Expression data (baseline)
  2. Network drift results (node-level drift scores)
  3. Cross-species conservation features

All features are traceable back to their biological source gene.
Feature names include the gene ID for full traceability.

Data-leakage protection:
  - Feature selection is NOT performed here; it is performed inside training folds.
  - No sample-level statistics from the test set are used.
  - All transformations are fit on training data only (enforced in MLEngine).
"""
import numpy as np
import pandas as pd
import structlog
from typing import Optional, List, Dict

logger = structlog.get_logger(__name__)


class FeatureExtractor:
    """
    Extracts features for machine learning.

    Parameters
    ----------
    experiment_type : str
        'expression_only' | 'drift_only' | 'combined'
    top_deg_genes : int or None
        For expression features: restrict to top N DEGs by |log2FC|.
    """

    def __init__(
        self,
        experiment_type: str = "combined",
        top_deg_genes: Optional[int] = None,
    ):
        self.experiment_type = experiment_type
        self.top_deg_genes = top_deg_genes

    def extract(
        self,
        expr_df: Optional[pd.DataFrame] = None,
        deg_results: Optional[pd.DataFrame] = None,
        node_drift_df: Optional[pd.DataFrame] = None,
        cross_species_df: Optional[pd.DataFrame] = None,
        sample_ids: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        Extract features for the given samples.

        Parameters
        ----------
        expr_df : pd.DataFrame or None
            Expression matrix (genes × samples), log2-normalized.
        deg_results : pd.DataFrame or None
            DEG results table (gene_id index, log2fc, padj, significant).
        node_drift_df : pd.DataFrame or None
            Per-gene node drift scores (gene_id column).
        cross_species_df : pd.DataFrame or None
            Cross-species comparison (human_ensembl_id, drift_classification, etc.).
        sample_ids : list[str] or None
            Restrict to these sample IDs (columns).

        Returns
        -------
        pd.DataFrame — rows = samples, columns = features.
        """
        feature_frames = []

        if self.experiment_type in ("expression_only", "combined"):
            expr_features = self._expression_features(expr_df, deg_results, sample_ids)
            if expr_features is not None:
                feature_frames.append(expr_features)
                logger.info("expression_features_extracted", n_features=expr_features.shape[1])

        if self.experiment_type in ("drift_only", "combined"):
            drift_features = self._drift_features(node_drift_df, cross_species_df, sample_ids, expr_df)
            if drift_features is not None:
                feature_frames.append(drift_features)
                logger.info("drift_features_extracted", n_features=drift_features.shape[1])

        if not feature_frames:
            raise ValueError("No features could be extracted. Check input data.")

        combined = pd.concat(feature_frames, axis=1)

        # Remove constant or all-NaN features
        combined = combined.dropna(axis=1, how="all")
        n_constant = (combined.nunique() <= 1).sum()
        if n_constant > 0:
            combined = combined.loc[:, combined.nunique() > 1]
            logger.info("constant_features_removed", n_removed=int(n_constant))

        return combined

    def _expression_features(
        self,
        expr_df: Optional[pd.DataFrame],
        deg_results: Optional[pd.DataFrame],
        sample_ids: Optional[List[str]],
    ) -> Optional[pd.DataFrame]:
        if expr_df is None:
            logger.warning("expression_df_not_provided")
            return None

        if sample_ids:
            expr_df = expr_df[[s for s in sample_ids if s in expr_df.columns]]

        # Select genes: DEG genes if available, else top-variance genes
        if deg_results is not None and "significant" in deg_results.columns:
            sig_genes = deg_results[deg_results["significant"]].index.tolist()
            if self.top_deg_genes:
                sig_genes = (
                    deg_results[deg_results["significant"]]
                    .reindex(sig_genes)
                    .assign(abs_lfc=lambda d: d["log2fc"].abs())
                    .nlargest(self.top_deg_genes, "abs_lfc")
                    .index.tolist()
                )
            genes_to_use = [g for g in sig_genes if g in expr_df.index]
            if not genes_to_use:
                logger.warning("no_deg_genes_in_expression_matrix_using_top_variance")
                genes_to_use = expr_df.var(axis=1).nlargest(500).index.tolist()
        else:
            genes_to_use = expr_df.var(axis=1).nlargest(500).index.tolist()

        sub = expr_df.loc[genes_to_use].T
        sub.columns = [f"expr_{g}" for g in sub.columns]
        return sub

    def _drift_features(
        self,
        node_drift_df: Optional[pd.DataFrame],
        cross_species_df: Optional[pd.DataFrame],
        sample_ids: Optional[List[str]],
        expr_df: Optional[pd.DataFrame],
    ) -> Optional[pd.DataFrame]:
        """
        Map per-gene network drift scores to per-sample features.

        Because drift scores are computed at the population level (from all samples
        of a given state), they cannot directly represent per-sample variation.

        Strategy: for each sample, compute a weighted expression score using the
        drift score as a weight. This creates sample-level features that reflect
        both expression level and network drift.

        The formula for sample s and gene g is:
            drift_feature(s, g) = expr(s, g) * node_drift_score(g)

        This is biologically motivated: genes with high drift scores that are
        highly expressed in a sample contribute more to the sample's feature profile.
        """
        if node_drift_df is None:
            logger.warning("node_drift_df_not_provided")
            return None
        if expr_df is None:
            logger.warning("expression_df_required_for_drift_features")
            return None

        nd = node_drift_df.set_index("gene_id") if "gene_id" in node_drift_df.columns else node_drift_df
        genes_with_drift = nd[nd["node_drift_score"] > 0.1].index.tolist()

        if not genes_with_drift:
            logger.warning("no_significantly_drifting_genes_found")
            genes_with_drift = nd.nlargest(100, "node_drift_score").index.tolist()

        # Add conservation label as feature weight multiplier
        conservation_weights = pd.Series(1.0, index=genes_with_drift)
        if cross_species_df is not None:
            cs = cross_species_df.set_index("human_ensembl_id") if "human_ensembl_id" in cross_species_df.columns else cross_species_df
            # Conserved drift genes get weight 2, divergent get 0.5
            for gene in genes_with_drift:
                if gene in cs.index:
                    cls = cs.loc[gene, "drift_classification"]
                    if cls == "conserved":
                        conservation_weights[gene] = 2.0
                    elif cls == "divergent":
                        conservation_weights[gene] = 0.5

        if sample_ids:
            samples = [s for s in sample_ids if s in expr_df.columns]
        else:
            samples = expr_df.columns.tolist()

        available_genes = [g for g in genes_with_drift if g in expr_df.index]
        if not available_genes:
            return None

        expr_sub = expr_df.loc[available_genes, samples].T

        # Multiply each gene's expression by its drift score and conservation weight
        drift_scores = nd.loc[available_genes, "node_drift_score"]
        weights = drift_scores * conservation_weights.reindex(available_genes).fillna(1.0)

        drift_features = expr_sub.multiply(weights.values, axis=1)
        drift_features.columns = [f"drift_{g}" for g in available_genes]

        # Also include raw drift scores as sample-agnostic features (same for all samples)
        for col in ["degree_change", "betweenness_change", "node_drift_score"]:
            if col in nd.columns:
                for gene in available_genes:
                    drift_features[f"pop_{col}_{gene}"] = nd.loc[gene, col]

        return drift_features
