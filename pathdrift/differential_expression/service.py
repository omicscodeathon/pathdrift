from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd

from .analysis import run_continuous_de, run_count_de
from .plots import write_deg_figures
from .validation import (
    ExpressionValidationError,
    ValidatedExpression,
    normalize_ensembl_id,
    validate_expression_inputs,
    validate_raw_counts,
)


def analyze_comparison(
    expression: pd.DataFrame,
    metadata: pd.DataFrame,
    *,
    raw_counts: pd.DataFrame | None,
    species: str,
    sample_id_column: str,
    condition_column: str,
    case_condition: str,
    control_condition: str,
    minimum_samples_per_group: int,
    alpha: float,
    lfc_threshold: float,
    data_type: str,
    method: str,
    min_count: int,
    min_samples_fraction: float,
    expression_scale: str,
    excluded_samples: set[str] | None = None,
    excluded_cases: set[str] | None = None,
    case_id_column: str | None = None,
    n_cpus: int = 1,
) -> tuple[pd.DataFrame, dict[str, Any], ValidatedExpression]:
    validated = validate_expression_inputs(
        expression,
        metadata,
        species=species,
        sample_id_column=sample_id_column,
        condition_column=condition_column,
        case_condition=case_condition,
        control_condition=control_condition,
        minimum_samples_per_group=minimum_samples_per_group,
        excluded_samples=excluded_samples,
        excluded_cases=excluded_cases,
        case_id_column=case_id_column,
    )
    declared_type = data_type.casefold()
    selected_method = method.casefold()
    if selected_method == "auto":
        selected_method = "count" if declared_type == "raw_counts" else "continuous"
    if selected_method == "count":
        if declared_type != "raw_counts" or raw_counts is None:
            raise ExpressionValidationError("Count-based DEG requires declared raw_counts and a raw count matrix.")
        count_matrix = raw_counts.copy()
        count_matrix.index = count_matrix.index.map(normalize_ensembl_id)
        count_matrix.columns = count_matrix.columns.map(str)
        if count_matrix.index.has_duplicates:
            raise ExpressionValidationError("Raw count matrix has duplicate Ensembl IDs after version normalization.")
        selected_samples = validated.control_samples + validated.case_samples
        if set(count_matrix.columns) != set(expression.columns.map(str)):
            raise ExpressionValidationError("Raw counts and QC-normalized expression have different sample IDs.")
        missing_qc_genes = set(validated.expression.index) - set(count_matrix.index)
        if missing_qc_genes:
            raise ExpressionValidationError(
                f"Raw count matrix is missing {len(missing_qc_genes)} genes retained by Phase 2 QC."
            )
        count_matrix = count_matrix.loc[validated.expression.index, selected_samples]
        count_matrix = validate_raw_counts(count_matrix)
        count_validated = ValidatedExpression(
            expression=count_matrix,
            metadata=validated.metadata,
            case_samples=validated.case_samples,
            control_samples=validated.control_samples,
            excluded_samples=validated.excluded_samples,
            invalid_gene_ids=validated.invalid_gene_ids,
            duplicate_gene_ids=[],
        )
        results, filtering = run_count_de(
            count_validated,
            min_count=min_count,
            min_samples_fraction=min_samples_fraction,
            alpha=alpha,
            lfc_threshold=lfc_threshold,
            n_cpus=n_cpus,
        )
    elif selected_method == "continuous":
        if declared_type == "raw_counts":
            raise ExpressionValidationError("Raw counts must not be analyzed as continuous normalized expression.")
        results, filtering = run_continuous_de(
            validated,
            alpha=alpha,
            lfc_threshold=lfc_threshold,
            scale=expression_scale,
        )
    else:
        raise ValueError("DE method must be 'auto', 'count', or 'continuous'.")
    summary = {
        **filtering,
        "species": species,
        "comparison": f"{case_condition}_vs_{control_condition}",
        "case_condition": case_condition,
        "control_condition": control_condition,
        "case_sample_count": len(validated.case_samples),
        "control_sample_count": len(validated.control_samples),
        "case_sample_ids": list(validated.case_samples),
        "control_sample_ids": list(validated.control_samples),
        "excluded_samples": list(validated.excluded_samples),
        "total_gene_rows_returned": int(len(results)),
        "total_genes_tested": int(results["pvalue"].notna().sum()),
        "genes_within_group_variance_unavailable": int(
            filtering.get("genes_within_group_variance_unavailable", 0)
        ),
        "significant_genes": int(results["significant"].sum()),
        "upregulated_genes": int(results["direction"].eq("UPREGULATED").sum()),
        "downregulated_genes": int(results["direction"].eq("DOWNREGULATED").sum()),
        "alpha": float(alpha),
        "lfc_threshold": float(lfc_threshold),
        "invalid_gene_ids_excluded": int(len(validated.invalid_gene_ids)),
        "selected_method_from_data_type": {
            "declared_data_type": declared_type,
            "configured_method": method,
            "selected_method": selected_method,
        },
        "expression_scale": "raw_counts" if selected_method == "count" else expression_scale,
    }
    return results, summary, validated


def write_deg_comparison(
    results: pd.DataFrame,
    summary: dict[str, Any],
    output_dir: Path,
    *,
    accession: str,
    alpha: float,
    lfc_threshold: float,
) -> list[dict[str, str]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results.to_csv(output_dir / "all_genes.csv", index=False)
    results.loc[results["significant"]].to_csv(output_dir / "significant_genes.csv", index=False)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )
    return write_deg_figures(
        results,
        output_dir,
        accession=accession,
        alpha=alpha,
        lfc_threshold=lfc_threshold,
        expression_scale=str(summary["expression_scale"]),
    )
