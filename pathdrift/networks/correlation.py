from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests


def correlation_edges(
    expression: pd.DataFrame,
    *,
    method: str,
    min_abs_correlation: float,
    max_adjusted_p_value: float,
) -> tuple[pd.DataFrame, dict[str, int | str | float]]:
    if method not in {"pearson", "spearman"}:
        raise ValueError(f"Unsupported correlation method: {method!r}")
    if not 0 <= min_abs_correlation <= 1 or not 0 < max_adjusted_p_value <= 1:
        raise ValueError("Correlation/FDR thresholds are outside their valid range.")
    x = expression.to_numpy(dtype=np.float64, copy=True)
    if x.shape[1] < 3:
        raise ValueError("Correlation networks require at least 3 aligned samples.")
    if not np.isfinite(x).all():
        raise ValueError("Correlation input contains missing or infinite expression values.")
    if method == "spearman":
        x = stats.rankdata(x, axis=1)
    centered = x - x.mean(axis=1, keepdims=True)
    norms = np.sqrt(np.sum(centered * centered, axis=1))
    variable = norms > 0
    expression = expression.loc[variable]
    centered = centered[variable]
    norms = norms[variable]
    if not len(norms):
        raise ValueError("No variable genes remain for correlation estimation.")
    standardized = centered / norms[:, None]
    n_genes, n_samples = standardized.shape
    pair_count = n_genes * (n_genes - 1) // 2
    # Compute the upper-triangle correlations in blocks to avoid a samples×genes×genes tensor.
    correlations = np.empty(pair_count, dtype=np.float64)
    cursor = 0
    block_size = 256
    for start in range(0, n_genes, block_size):
        stop = min(start + block_size, n_genes)
        block = standardized[start:stop] @ standardized.T
        for row_offset, gene_index in enumerate(range(start, stop)):
            row_values = block[row_offset, gene_index + 1:]
            end = cursor + len(row_values)
            correlations[cursor:end] = row_values
            cursor = end
        del block
    if cursor != pair_count:
        raise RuntimeError(f"Internal correlation count mismatch: expected {pair_count}, got {cursor}.")
    np.clip(correlations, -1.0, 1.0, out=correlations)

    degrees_freedom = n_samples - 2
    denominator = np.maximum(1.0 - correlations * correlations, np.finfo(float).eps)
    with np.errstate(over="ignore", invalid="ignore"):
        t_values = np.abs(correlations) * np.sqrt(degrees_freedom / denominator)
    p_values = 2.0 * stats.t.sf(t_values, degrees_freedom)
    _, adjusted_p, _, _ = multipletests(p_values, method="fdr_bh")
    keep = (np.abs(correlations) >= min_abs_correlation) & (adjusted_p <= max_adjusted_p_value)

    gene_ids = expression.index.astype(str).to_numpy()
    if keep.any():
        kept_positions = np.flatnonzero(keep)
        row_starts = np.cumsum(
            np.r_[0, np.arange(n_genes - 1, 0, -1, dtype=np.int64)],
            dtype=np.int64,
        )
        rows = np.searchsorted(row_starts, kept_positions, side="right") - 1
        cols = rows + 1 + kept_positions - row_starts[rows]
        left_ids, right_ids = gene_ids[rows], gene_ids[cols]
        correlations_kept = correlations[kept_positions]
        edges = pd.DataFrame({
            "source_gene": np.minimum(left_ids, right_ids),
            "target_gene": np.maximum(left_ids, right_ids),
            "correlation": correlations_kept,
            "absolute_correlation": np.abs(correlations_kept),
            "p_value": p_values[kept_positions],
            "adjusted_p_value": adjusted_p[kept_positions],
            "weight": np.abs(correlations_kept),
        })
    else:
        edges = pd.DataFrame(columns=[
            "source_gene", "target_gene", "correlation", "absolute_correlation",
            "p_value", "adjusted_p_value", "weight",
        ])
    return edges, {
        "method": method,
        "tested_gene_pairs": int(pair_count),
        "edges_passing_correlation_threshold": int((np.abs(correlations) >= min_abs_correlation).sum()),
        "edges_retained": int(len(edges)),
        "min_abs_correlation": float(min_abs_correlation),
        "max_adjusted_p_value": float(max_adjusted_p_value),
        "fdr_method": "Benjamini-Hochberg",
        "p_value_method": (
            "Two-sided t approximation with n-2 degrees of freedom applied to "
            f"{method} correlations"
        ),
        "sample_count": int(n_samples),
    }
