"""
Differential Expression Analysis Engine

Supports:
  - DESeq2-style analysis via pydeseq2 (raw count data)
  - Welch's t-test + Benjamini-Hochberg FDR (normalized/microarray data)
  - Fold change calculation from log2-normalized data

Returns per-gene statistics: log2FC, p-value, adjusted p-value, mean expression per group.
"""
import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
import structlog
from typing import Optional, Tuple

logger = structlog.get_logger(__name__)


class DEGAnalyzer:
    """
    Performs differential expression analysis between two groups.

    Parameters
    ----------
    method : str
        'pydeseq2' for raw counts, 'ttest' for normalized data
    fdr_threshold : float
        Adjusted p-value cutoff for significance
    lfc_threshold : float
        |log2FC| threshold for significance
    """

    def __init__(
        self,
        method: str = "ttest",
        fdr_threshold: float = 0.05,
        lfc_threshold: float = 1.0,
    ):
        self.method = method
        self.fdr_threshold = fdr_threshold
        self.lfc_threshold = lfc_threshold

    def run(
        self,
        expr_df: pd.DataFrame,
        healthy_samples: list[str],
        disease_samples: list[str],
    ) -> pd.DataFrame:
        """
        Run DEG analysis.

        Parameters
        ----------
        expr_df : pd.DataFrame
            Expression matrix (genes × samples). For pydeseq2: raw counts.
            For ttest: normalized log2 values.
        healthy_samples, disease_samples : list[str]
            Sample column names for each group.

        Returns
        -------
        pd.DataFrame with columns:
            gene_id, log2fc, mean_healthy, mean_disease,
            pvalue, padj, significant, direction
        """
        missing_h = set(healthy_samples) - set(expr_df.columns)
        missing_d = set(disease_samples) - set(expr_df.columns)
        if missing_h or missing_d:
            raise ValueError(
                f"Samples not found in expression matrix: "
                f"healthy={missing_h}, disease={missing_d}"
            )

        if self.method == "pydeseq2":
            return self._pydeseq2(expr_df, healthy_samples, disease_samples)
        else:
            return self._ttest(expr_df, healthy_samples, disease_samples)

    def _ttest(
        self,
        expr_df: pd.DataFrame,
        healthy_samples: list[str],
        disease_samples: list[str],
    ) -> pd.DataFrame:
        """Welch's t-test on (assumed log2-normalized) expression data."""
        logger.info("deg_ttest_starting", n_genes=len(expr_df))

        h = expr_df[healthy_samples].values
        d = expr_df[disease_samples].values

        mean_h = h.mean(axis=1)
        mean_d = d.mean(axis=1)
        log2fc = mean_d - mean_h  # log2 scale: difference = log2FC

        _, pvalues = stats.ttest_ind(d, h, axis=1, equal_var=False)

        # Replace NaN p-values (e.g. zero variance) with 1
        pvalues = np.where(np.isnan(pvalues), 1.0, pvalues)

        reject, padj, _, _ = multipletests(pvalues, method="fdr_bh")

        results = pd.DataFrame(
            {
                "gene_id": expr_df.index,
                "log2fc": log2fc,
                "mean_healthy": mean_h,
                "mean_disease": mean_d,
                "pvalue": pvalues,
                "padj": padj,
            }
        ).set_index("gene_id")

        results["significant"] = (
            (results["padj"] <= self.fdr_threshold)
            & (results["log2fc"].abs() >= self.lfc_threshold)
        )
        results["direction"] = np.where(
            results["log2fc"] > 0, "up", "down"
        )
        results["direction"] = results["direction"].where(results["significant"], "ns")

        n_sig = results["significant"].sum()
        logger.info(
            "deg_ttest_done",
            n_significant=int(n_sig),
            n_up=int((results["direction"] == "up").sum()),
            n_down=int((results["direction"] == "down").sum()),
        )
        return results.sort_values("padj")

    def _pydeseq2(
        self,
        counts_df: pd.DataFrame,
        healthy_samples: list[str],
        disease_samples: list[str],
    ) -> pd.DataFrame:
        """DESeq2-style analysis via pydeseq2."""
        try:
            from pydeseq2.dds import DeseqDataSet
            from pydeseq2.ds import DeseqStats
        except ImportError:
            logger.warning("pydeseq2_not_available_falling_back_to_ttest")
            return self._ttest(counts_df, healthy_samples, disease_samples)

        logger.info("deg_pydeseq2_starting", n_genes=len(counts_df))

        # pydeseq2 expects: samples as rows, genes as columns; integer counts
        all_samples = healthy_samples + disease_samples
        counts = counts_df[all_samples].T.round(0).astype(int)
        metadata = pd.DataFrame(
            {"condition": ["healthy"] * len(healthy_samples) + ["disease"] * len(disease_samples)},
            index=all_samples,
        )

        try:
            dds = DeseqDataSet(
                counts=counts,
                metadata=metadata,
                design_factors="condition",
                refit_cooks=True,
                n_cpus=1,
            )
            dds.deseq2()
            stat_res = DeseqStats(dds, contrast=["condition", "disease", "healthy"], n_cpus=1)
            stat_res.summary()
            res = stat_res.results_df.copy()
        except Exception as e:
            logger.warning("pydeseq2_failed_falling_back_to_ttest", error=str(e))
            return self._ttest(counts_df, healthy_samples, disease_samples)

        # Harmonize column names
        res = res.rename(
            columns={
                "log2FoldChange": "log2fc",
                "pvalue": "pvalue",
                "padj": "padj",
                "baseMean": "base_mean",
            }
        )
        res.index.name = "gene_id"
        res["mean_healthy"] = counts_df[healthy_samples].mean(axis=1)
        res["mean_disease"] = counts_df[disease_samples].mean(axis=1)
        res["significant"] = (
            (res["padj"] <= self.fdr_threshold)
            & (res["log2fc"].abs() >= self.lfc_threshold)
            & res["padj"].notna()
        )
        res["direction"] = np.where(res["log2fc"] > 0, "up", "down")
        res["direction"] = res["direction"].where(res["significant"], "ns")

        n_sig = res["significant"].sum()
        logger.info(
            "deg_pydeseq2_done",
            n_significant=int(n_sig),
            n_up=int((res["direction"] == "up").sum()),
            n_down=int((res["direction"] == "down").sum()),
        )
        return res.sort_values("padj")
