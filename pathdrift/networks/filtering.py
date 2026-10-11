from __future__ import annotations

import pandas as pd


def select_network_genes(
    expression: pd.DataFrame,
    *,
    min_variance: float,
    max_genes: int,
) -> tuple[pd.DataFrame, dict[str, int | float]]:
    if min_variance < 0 or max_genes < 2:
        raise ValueError("Network filtering requires non-negative variance and max_genes >= 2.")
    variance = expression.var(axis=1, ddof=1)
    variable = expression.loc[variance >= min_variance].copy()
    if variable.empty:
        raise ValueError("No genes remain after the configured minimum-variance filter.")
    before_cap = len(variable)
    if before_cap > max_genes:
        variable = variable.loc[variance.loc[variable.index].nlargest(max_genes).index]
    return variable, {
        "genes_input": int(len(expression)),
        "genes_after_variance": int(before_cap),
        "genes_used": int(len(variable)),
        "min_gene_variance": float(min_variance),
        "max_genes": int(max_genes),
        "genes_limited_by_variance_rank": max(0, before_cap - len(variable)),
    }
