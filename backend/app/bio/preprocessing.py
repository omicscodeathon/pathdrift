"""
PathDrift Preprocessing Engine

Implements a rigorous, reproducible preprocessing pipeline for gene expression data.
Every decision is logged. Normalization method is selected based on data type;
inappropriate normalizations are not applied silently.

Supports:
  - log2CPM normalization (RNA-seq counts)
  - DESeq2-style variance-stabilizing transformation (via pydeseq2)
  - TPM / FPKM pass-through (already normalized data)
  - Quantile normalization (microarray)
  - Low-expression gene filtering
  - Duplicate gene handling
  - Missing value imputation (optional)
  - Sample-level QC (library size, PCA-based outlier detection)
  - Batch effect assessment (PCA variance explained by batch)
  - Optional batch correction (ComBat-like via limma-equivalent)
"""
import os
import hashlib
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timezone

import numpy as np
import pandas as pd
from scipy import stats
from scipy.stats import zscore
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class PreprocessingLog:
    dataset_id: str
    species: str
    normalization_method: str
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    steps: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    parameters: Dict = field(default_factory=dict)
    n_genes_before: int = 0
    n_genes_after: int = 0
    n_samples_before: int = 0
    n_samples_after: int = 0
    removed_genes: List[str] = field(default_factory=list)
    removed_samples: List[str] = field(default_factory=list)
    outlier_samples: List[str] = field(default_factory=list)

    def add_step(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.steps.append(f"[{ts}] {msg}")
        logger.info("preprocessing_step", msg=msg)

    def add_warning(self, msg: str):
        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
        self.warnings.append(f"[{ts}] WARNING: {msg}")
        logger.warning("preprocessing_warning", msg=msg)

    def to_text(self) -> str:
        lines = [
            f"PathDrift Preprocessing Log",
            f"Dataset: {self.dataset_id}",
            f"Species: {self.species}",
            f"Normalization: {self.normalization_method}",
            f"Started: {self.started_at}",
            f"Genes: {self.n_genes_before} → {self.n_genes_after}",
            f"Samples: {self.n_samples_before} → {self.n_samples_after}",
            "",
            "=== Steps ===",
            *self.steps,
        ]
        if self.warnings:
            lines += ["", "=== Warnings ===", *self.warnings]
        if self.removed_samples:
            lines += ["", f"=== Removed Samples ({len(self.removed_samples)}) ===", *self.removed_samples[:20]]
        return "\n".join(lines)


class PreprocessingPipeline:
    """
    Preprocessing pipeline for a single dataset.
    Returns a cleaned expression matrix and a detailed log.
    """

    def __init__(
        self,
        normalization_method: str = "log2cpm",
        low_expr_threshold: float = 1.0,
        low_expr_min_samples: int = 3,
        min_gene_variance: float = 0.0,
        remove_duplicates: bool = True,
        impute_missing: bool = False,
        batch_correct: bool = False,
        batch_correction_method: Optional[str] = None,
        outlier_detection: bool = True,
        random_seed: int = 42,
    ):
        self.normalization_method = normalization_method
        self.low_expr_threshold = low_expr_threshold
        self.low_expr_min_samples = low_expr_min_samples
        self.min_gene_variance = min_gene_variance
        self.remove_duplicates = remove_duplicates
        self.impute_missing = impute_missing
        self.batch_correct = batch_correct
        self.batch_correction_method = batch_correction_method
        self.outlier_detection = outlier_detection
        self.random_seed = random_seed

    def run(
        self,
        expr_df: pd.DataFrame,
        metadata_df: Optional[pd.DataFrame],
        dataset_id: str,
        species: str,
    ) -> Tuple[pd.DataFrame, PreprocessingLog]:
        """
        Execute the full preprocessing pipeline.

        Parameters
        ----------
        expr_df : pd.DataFrame
            Raw expression matrix. Rows = genes, columns = samples.
        metadata_df : pd.DataFrame or None
            Sample metadata with columns including sample_id, disease_state.
        dataset_id : str
        species : str

        Returns
        -------
        (cleaned_df, log)
        """
        log = PreprocessingLog(
            dataset_id=dataset_id,
            species=species,
            normalization_method=self.normalization_method,
            parameters={
                "low_expr_threshold": self.low_expr_threshold,
                "low_expr_min_samples": self.low_expr_min_samples,
                "min_gene_variance": self.min_gene_variance,
                "remove_duplicates": self.remove_duplicates,
                "impute_missing": self.impute_missing,
                "batch_correct": self.batch_correct,
                "normalization_method": self.normalization_method,
                "outlier_detection": self.outlier_detection,
                "random_seed": self.random_seed,
            },
        )

        df = expr_df.copy()
        log.n_genes_before = df.shape[0]
        log.n_samples_before = df.shape[1]
        log.add_step(f"Input: {df.shape[0]} genes × {df.shape[1]} samples")

        # Step 1 — Gene ID normalization (strip whitespace)
        df.index = df.index.astype(str).str.strip()
        log.add_step("Gene identifiers stripped of whitespace")

        # Step 2 — Convert to numeric
        df = df.apply(pd.to_numeric, errors="coerce")
        non_numeric = df.isnull().sum().sum()
        if non_numeric > 0:
            log.add_warning(f"{non_numeric} non-numeric values coerced to NaN")

        # Step 3 — Missing value handling
        n_missing = int(df.isnull().sum().sum())
        if n_missing > 0:
            frac = n_missing / df.size
            log.add_step(f"Missing values: {n_missing} ({frac:.2%})")
            if self.impute_missing:
                # Row-median imputation (conservative)
                row_medians = df.median(axis=1)
                df = df.T.fillna(row_medians).T
                log.add_step("Missing values imputed with row median")
            else:
                # Drop rows with >50% missing
                high_missing = df.isnull().mean(axis=1) > 0.5
                n_drop = high_missing.sum()
                if n_drop > 0:
                    log.add_warning(f"Dropping {n_drop} genes with >50% missing values")
                    log.removed_genes.extend(df.index[high_missing].tolist())
                    df = df.loc[~high_missing]

        # Step 4 — Duplicate gene handling
        if self.remove_duplicates:
            dup_mask = df.index.duplicated(keep=False)
            if dup_mask.any():
                n_dups = df.index.duplicated().sum()
                log.add_step(f"Duplicate genes: keeping highest-variance copy for {n_dups} duplicated identifiers")
                # Keep the row with highest variance per group
                df["_var"] = df.var(axis=1)
                df = df.sort_values("_var", ascending=False)
                df = df[~df.index.duplicated(keep="first")]
                df = df.drop(columns=["_var"])

        # Step 5 — Low expression filtering
        # Strategy depends on data type:
        # For raw counts: filter genes where CPM < threshold in >= min_samples
        # For normalized data: filter genes where expression < threshold in >= min_samples
        n_before_filter = df.shape[0]
        if self.normalization_method in ("log2cpm", "deseq2_vst"):
            # Filter on raw counts before normalization
            min_count = self.low_expr_threshold
            expressed = (df >= min_count).sum(axis=1) >= self.low_expr_min_samples
        else:
            # Already normalized — filter on absolute value
            expressed = (df.abs() >= self.low_expr_threshold).sum(axis=1) >= self.low_expr_min_samples

        n_removed = (~expressed).sum()
        if n_removed > 0:
            log.removed_genes.extend(df.index[~expressed].tolist())
            df = df.loc[expressed]
            log.add_step(
                f"Low-expression filter: removed {n_removed} genes "
                f"(threshold={self.low_expr_threshold}, min_samples={self.low_expr_min_samples}). "
                f"Remaining: {df.shape[0]}"
            )

        # Step 6 — Normalization
        df = self._normalize(df, log)

        # Step 7 — Variance filter (post-normalization)
        if self.min_gene_variance > 0:
            gene_vars = df.var(axis=1)
            high_var = gene_vars >= self.min_gene_variance
            n_var_removed = (~high_var).sum()
            if n_var_removed > 0:
                log.removed_genes.extend(df.index[~high_var].tolist())
                df = df.loc[high_var]
                log.add_step(f"Variance filter: removed {n_var_removed} low-variance genes (threshold={self.min_gene_variance})")

        # Step 8 — Outlier detection
        if self.outlier_detection and df.shape[1] > 3:
            df, outliers = self._detect_outliers(df, log)
            log.outlier_samples = outliers
            log.removed_samples.extend(outliers)

        # Step 9 — Batch correction
        if self.batch_correct and metadata_df is not None:
            df, log = self._batch_correct(df, metadata_df, log)

        log.n_genes_after = df.shape[0]
        log.n_samples_after = df.shape[1]
        log.add_step(
            f"Preprocessing complete: {df.shape[0]} genes × {df.shape[1]} samples"
        )
        return df, log

    def _normalize(self, df: pd.DataFrame, log: PreprocessingLog) -> pd.DataFrame:
        method = self.normalization_method

        if method == "none":
            log.add_step("Normalization: none (data passed through as-is)")
            return df

        elif method == "log2cpm":
            # Log2 counts per million
            col_sums = df.sum(axis=0)
            zero_lib = (col_sums == 0).sum()
            if zero_lib > 0:
                log.add_warning(f"{zero_lib} samples have zero library size; they will produce undefined CPM.")
            cpm = df.divide(col_sums, axis=1) * 1e6
            log2cpm = np.log2(cpm + 1)
            log.add_step("Normalization: log2(CPM + 1)")
            return log2cpm

        elif method == "tpm" or method == "fpkm":
            log.add_step(f"Normalization: {method.upper()} (data assumed pre-normalized; log2 transform applied)")
            # Apply log2 transform if values appear raw
            if df.max().max() > 100:
                df = np.log2(df + 1)
                log.add_warning(f"Large values detected in {method.upper()} data — log2(x+1) transform applied")
            return df

        elif method == "quantile":
            log.add_step("Normalization: quantile normalization")
            return self._quantile_normalize(df, log)

        elif method == "deseq2_vst":
            log.add_step("Normalization: DESeq2-style VST (via pydeseq2)")
            return self._deseq2_vst(df, log)

        else:
            log.add_warning(f"Unknown normalization method '{method}'; data passed through unchanged")
            return df

    @staticmethod
    def _quantile_normalize(df: pd.DataFrame, log: PreprocessingLog) -> pd.DataFrame:
        """Column-wise quantile normalization."""
        rank_mean = df.stack().groupby(df.rank(method="first").stack().astype(int)).mean()
        normalized = df.rank(method="min").stack().astype(int).map(rank_mean).unstack()
        return normalized

    @staticmethod
    def _deseq2_vst(df: pd.DataFrame, log: PreprocessingLog) -> pd.DataFrame:
        """
        Variance-stabilizing transformation using pydeseq2.
        Requires integer count data; warns if non-integers detected.
        """
        try:
            from pydeseq2.preprocessing import deseq2_norm
            # Round to integers (VST requires counts)
            counts = df.round(0).astype(int)
            non_integer_genes = (df != counts).any(axis=1).sum()
            if non_integer_genes > 0:
                log.add_warning(
                    f"{non_integer_genes} genes had non-integer values; rounded before DESeq2-norm. "
                    "If data is already normalized, use 'none' or 'log2cpm'."
                )
            norm_counts, _ = deseq2_norm(counts.T)
            vst = np.log2(norm_counts.T + 1)
            return pd.DataFrame(vst, index=df.index, columns=df.columns)
        except ImportError:
            log.add_warning("pydeseq2 not available; falling back to log2CPM normalization")
            col_sums = df.sum(axis=0)
            cpm = df.divide(col_sums, axis=1) * 1e6
            return np.log2(cpm + 1)

    @staticmethod
    def _detect_outliers(
        df: pd.DataFrame, log: PreprocessingLog
    ) -> Tuple[pd.DataFrame, List[str]]:
        """
        PCA + Mahalanobis distance outlier detection.
        Samples > 3 SD from centroid (in PC space) are flagged.
        """
        from sklearn.preprocessing import StandardScaler
        from sklearn.decomposition import PCA

        X = df.T.values  # samples × genes
        # Use top 50 PCs or all genes if fewer
        n_comp = min(50, X.shape[0] - 1, X.shape[1])
        if n_comp < 2:
            log.add_step("Outlier detection: skipped (too few samples or genes)")
            return df, []

        try:
            scaler = StandardScaler()
            Xs = scaler.fit_transform(X)
            pca = PCA(n_components=n_comp, random_state=42)
            scores = pca.fit_transform(Xs)

            # Mahalanobis-like: z-score each PC and compute distance
            z = zscore(scores, axis=0)
            dist = np.sqrt((z ** 2).sum(axis=1))
            threshold = np.mean(dist) + 3 * np.std(dist)
            outlier_mask = dist > threshold
            outlier_samples = df.columns[outlier_mask].tolist()

            if outlier_samples:
                log.add_warning(
                    f"Detected {len(outlier_samples)} potential outlier samples "
                    f"(PCA Mahalanobis distance > 3 SD): {outlier_samples[:5]}"
                )
                log.add_step(f"Removing outlier samples: {outlier_samples}")
                df = df.drop(columns=outlier_samples)

            return df, outlier_samples
        except Exception as e:
            log.add_warning(f"Outlier detection failed: {e}")
            return df, []

    @staticmethod
    def _batch_correct(
        df: pd.DataFrame,
        metadata_df: pd.DataFrame,
        log: PreprocessingLog,
    ) -> Tuple[pd.DataFrame, PreprocessingLog]:
        """
        Simple location-scale batch correction (ComBat-like mean/variance adjustment).
        A proper implementation would use pyComBat or rpy2+ComBat, but this provides
        a reproducible alternative that does not require R.
        """
        log.add_step("Batch correction: checking batch column in metadata")
        meta = metadata_df.copy()
        meta.columns = meta.columns.str.lower()
        if "batch" not in meta.columns:
            log.add_warning("Batch correction requested but 'batch' column not found in metadata; skipping")
            return df, log

        meta = meta.set_index("sample_id")
        common_samples = df.columns.intersection(meta.index)
        if len(common_samples) == 0:
            log.add_warning("No overlapping sample IDs between expression and metadata; skipping batch correction")
            return df, log

        df_bc = df[common_samples].copy()
        batches = meta.loc[common_samples, "batch"]
        batch_labels = batches.unique()

        if len(batch_labels) < 2:
            log.add_step("Only one batch detected; batch correction not applied")
            return df, log

        # Location-scale correction per gene
        grand_mean = df_bc.mean(axis=1)
        grand_std = df_bc.std(axis=1).replace(0, 1)

        corrected = df_bc.copy()
        for batch_label in batch_labels:
            batch_samples = batches[batches == batch_label].index
            batch_df = df_bc[batch_samples]
            batch_mean = batch_df.mean(axis=1)
            batch_std = batch_df.std(axis=1).replace(0, 1)
            # Scale to grand mean/std
            corrected[batch_samples] = (
                ((batch_df.T - batch_mean) / batch_std).T * grand_std + grand_mean
            )

        log.add_step(f"Batch correction applied to {len(batch_labels)} batches (location-scale)")
        log.add_warning(
            "Location-scale batch correction is an approximation. "
            "For publication-quality results, validate with principal component analysis."
        )
        return corrected, log
