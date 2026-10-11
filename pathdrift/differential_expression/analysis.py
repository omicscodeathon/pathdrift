from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests

from .preprocessing import filter_raw_counts
from .validation import ValidatedExpression


RESULT_COLUMNS = [
    "gene_id", "log2fc", "pvalue", "adjusted_p_value", "statistic",
    "base_mean", "average_expression", "direction", "significant", "method",
]


def _classify(
    results: pd.DataFrame,
    *,
    alpha: float,
    lfc_threshold: float,
    case_mean: pd.Series,
    control_mean: pd.Series,
    method: str,
) -> pd.DataFrame:
    results["significant"] = (
        results["adjusted_p_value"].notna()
        & (results["adjusted_p_value"] <= alpha)
        & (results["log2fc"].abs() >= lfc_threshold)
    )
    results["direction"] = "NOT_SIGNIFICANT"
    results.loc[results["significant"] & (results["log2fc"] > 0), "direction"] = "UPREGULATED"
    results.loc[results["significant"] & (results["log2fc"] < 0), "direction"] = "DOWNREGULATED"
    results["base_mean"] = np.nan
    results["average_expression"] = (case_mean + control_mean) / 2
    results["method"] = method
    return results.reset_index(names="gene_id")[RESULT_COLUMNS].sort_values(
        ["adjusted_p_value", "pvalue"], na_position="last"
    ).reset_index(drop=True)


def run_count_de(
    validated: ValidatedExpression,
    *,
    min_count: int,
    min_samples_fraction: float,
    alpha: float,
    lfc_threshold: float,
    n_cpus: int = 1,
) -> tuple[pd.DataFrame, dict]:
    counts, filtering = filter_raw_counts(
        validated,
        min_count=min_count,
        min_samples_fraction=min_samples_fraction,
    )
    try:
        from pydeseq2.dds import DeseqDataSet
        from pydeseq2.ds import DeseqStats
    except ImportError as exc:
        raise RuntimeError(
            "Raw-count DEG requires the configured PyDESeq2 dependency; no statistical fallback was used."
        ) from exc

    sample_ids = validated.control_samples + validated.case_samples
    sample_conditions = (
        [validated.metadata.loc[sample_id, "disease_state"] for sample_id in validated.control_samples]
        + [validated.metadata.loc[sample_id, "disease_state"] for sample_id in validated.case_samples]
    )
    condition_names = [str(value).casefold() for value in sample_conditions]
    control_condition = condition_names[0]
    case_condition = condition_names[-1]
    sample_metadata = pd.DataFrame(
        {"condition": condition_names},
        index=sample_ids,
    )
    count_samples = counts.loc[:, sample_ids].T
    dds = DeseqDataSet(
        counts=count_samples,
        metadata=sample_metadata,
        design_factors="condition",
        refit_cooks=False,
        n_cpus=n_cpus,
        quiet=True,
    )
    dds.deseq2()
    de_stats = DeseqStats(
        dds,
        contrast=["condition", case_condition, control_condition],
        alpha=alpha,
        quiet=True,
    )
    de_stats.summary()
    de = de_stats.results_df.copy()
    required = {"log2FoldChange", "pvalue", "padj", "stat", "baseMean"}
    missing = required.difference(de.columns)
    if missing:
        raise RuntimeError(f"PyDESeq2 omitted expected result columns: {sorted(missing)}")
    de = de.rename(columns={
        "log2FoldChange": "log2fc",
        "pvalue": "pvalue",
        "padj": "adjusted_p_value",
        "stat": "statistic",
        "baseMean": "base_mean",
    })
    de["average_expression"] = de["base_mean"]
    de["method"] = "PyDESeq2 (DESeq2 Wald test)"
    de["significant"] = (
        de["adjusted_p_value"].notna()
        & (de["adjusted_p_value"] <= alpha)
        & (de["log2fc"].abs() >= lfc_threshold)
    )
    de["direction"] = "NOT_SIGNIFICANT"
    de.loc[de["significant"] & (de["log2fc"] > 0), "direction"] = "UPREGULATED"
    de.loc[de["significant"] & (de["log2fc"] < 0), "direction"] = "DOWNREGULATED"
    de.index.name = "gene_id"
    result = de.reset_index()[RESULT_COLUMNS].sort_values(
        ["adjusted_p_value", "pvalue"], na_position="last"
    ).reset_index(drop=True)
    filtering.update({
        "tested_genes": int(len(result)),
        "method": "PyDESeq2 (DESeq2 Wald test)",
        "fdr_method": "Benjamini-Hochberg",
        "case_samples": len(validated.case_samples),
        "control_samples": len(validated.control_samples),
    })
    return result, filtering


def run_continuous_de(
    validated: ValidatedExpression,
    *,
    alpha: float,
    lfc_threshold: float,
    scale: str,
) -> tuple[pd.DataFrame, dict]:
    if scale not in {"log2", "linear"}:
        raise ValueError("Continuous expression scale must be explicitly configured as 'log2' or 'linear'.")
    case = validated.expression.loc[:, validated.case_samples].astype(float)
    control = validated.expression.loc[:, validated.control_samples].astype(float)
    if scale == "linear" and ((case < 0).any().any() or (control < 0).any().any()):
        raise ValueError("Linear normalized expression must be non-negative for log2 fold-change calculation.")
    case_values = case.to_numpy()
    control_values = control.to_numpy()
    case_mean = case.mean(axis=1)
    control_mean = control.mean(axis=1)
    case_variance = np.var(case_values, axis=1, ddof=1)
    control_variance = np.var(control_values, axis=1, ddof=1)
    variance_tolerance = (
        np.finfo(float).eps
        * 100
        * np.maximum.reduce([
            np.square(case_mean.to_numpy()),
            np.square(control_mean.to_numpy()),
            np.ones(len(case), dtype=float),
        ])
    )
    case_variance = np.where(case_variance <= variance_tolerance, 0.0, case_variance)
    control_variance = np.where(control_variance <= variance_tolerance, 0.0, control_variance)
    case_term = case_variance / case.shape[1]
    control_term = control_variance / control.shape[1]
    standard_error_squared = case_term + control_term
    testable = np.isfinite(standard_error_squared) & (standard_error_squared > 0)
    statistics = np.full(len(case), np.nan, dtype=float)
    degrees_freedom = np.full(len(case), np.nan, dtype=float)
    statistics[testable] = (
        (case_mean.to_numpy() - control_mean.to_numpy())[testable]
        / np.sqrt(standard_error_squared[testable])
    )
    denominator = (
        case_term * case_term / (case.shape[1] - 1)
        + control_term * control_term / (control.shape[1] - 1)
    )
    valid_degrees = testable & np.isfinite(denominator) & (denominator > 0)
    degrees_freedom[valid_degrees] = (
        standard_error_squared[valid_degrees] ** 2 / denominator[valid_degrees]
    )
    pvalues = np.full(len(case), np.nan, dtype=float)
    valid_tests = valid_degrees & np.isfinite(statistics) & np.isfinite(degrees_freedom)
    pvalues[valid_tests] = 2.0 * stats.t.sf(
        np.abs(statistics[valid_tests]),
        degrees_freedom[valid_tests],
    )
    finite_pvalues = np.isfinite(pvalues)
    adjusted = np.full_like(pvalues, np.nan)
    if finite_pvalues.any():
        adjusted[finite_pvalues] = multipletests(pvalues[finite_pvalues], method="fdr_bh")[1]
    if scale == "log2":
        log2fc = case_mean - control_mean
        average = (case_mean + control_mean) / 2
    else:
        log2fc = np.log2(case_mean + 1) - np.log2(control_mean + 1)
        average = (case_mean + control_mean) / 2
    frame = pd.DataFrame({
        "log2fc": log2fc,
        "pvalue": pvalues,
        "adjusted_p_value": adjusted,
        "statistic": statistics,
    }, index=validated.expression.index)
    results = _classify(
        frame,
        alpha=alpha,
        lfc_threshold=lfc_threshold,
        case_mean=case_mean,
        control_mean=control_mean,
        method="Welch's t-test + Benjamini-Hochberg",
    )
    results["average_expression"] = average.reindex(results["gene_id"]).to_numpy()
    return results, {
        "tested_genes": int(finite_pvalues.sum()),
        "genes_within_group_variance_unavailable": int((~valid_tests).sum()),
        "gene_rows_returned": int(len(results)),
        "method": "Welch's t-test + Benjamini-Hochberg",
        "fdr_method": "Benjamini-Hochberg",
        "expression_scale": scale,
        "case_samples": len(validated.case_samples),
        "control_samples": len(validated.control_samples),
        "genes_without_within_group_variance": int((~valid_tests).sum()),
    }
