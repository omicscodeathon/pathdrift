from __future__ import annotations

import math
import re
from dataclasses import dataclass

import numpy as np
import pandas as pd


IDENTIFIER_PATTERNS = {
    "human": re.compile(r"^ENSG\d+(?:_PAR_Y)?$"),
    "mouse": re.compile(r"^ENSMUSG\d+$"),
}
VERSION_SUFFIX = re.compile(r"^(ENS(?:G|MUSG)\d+)(?:\.\d+)(?=_PAR_Y$|$)")


class ExpressionValidationError(ValueError):
    pass


@dataclass(frozen=True)
class ValidatedExpression:
    expression: pd.DataFrame
    metadata: pd.DataFrame
    case_samples: list[str]
    control_samples: list[str]
    excluded_samples: list[str]
    invalid_gene_ids: list[str]
    duplicate_gene_ids: list[str]


def normalize_ensembl_id(value: object) -> str:
    gene_id = str(value).strip()
    return VERSION_SUFFIX.sub(r"\1", gene_id)


def validate_expression_inputs(
    expression: pd.DataFrame,
    metadata: pd.DataFrame,
    *,
    species: str,
    sample_id_column: str,
    condition_column: str,
    case_condition: str,
    control_condition: str,
    minimum_samples_per_group: int,
    excluded_samples: set[str] | None = None,
    excluded_cases: set[str] | None = None,
    case_id_column: str | None = None,
) -> ValidatedExpression:
    if expression.empty or not expression.columns.size:
        raise ExpressionValidationError("Expression matrix has no genes or samples.")
    if metadata.empty:
        raise ExpressionValidationError("Sample metadata is empty.")
    if sample_id_column not in metadata or condition_column not in metadata:
        raise ExpressionValidationError(
            f"Metadata must contain {sample_id_column!r} and {condition_column!r}."
        )

    matrix = expression.copy()
    matrix.columns = matrix.columns.map(str)
    matrix.index = matrix.index.map(normalize_ensembl_id)
    if matrix.columns.has_duplicates:
        raise ExpressionValidationError("Expression matrix contains duplicate sample columns.")
    if matrix.index.has_duplicates:
        duplicates = sorted(set(matrix.index[matrix.index.duplicated(keep=False)]))
        raise ExpressionValidationError(
            f"Expression matrix has duplicate gene identifiers after Ensembl version normalization: {duplicates[:10]}"
        )

    metadata = metadata.copy()
    metadata[sample_id_column] = metadata[sample_id_column].astype(str).str.strip()
    if metadata[sample_id_column].eq("").any() or metadata[sample_id_column].duplicated().any():
        raise ExpressionValidationError("Metadata sample IDs must be non-empty and unique.")
    matrix_ids = set(matrix.columns)
    metadata_ids = set(metadata[sample_id_column])
    if matrix_ids != metadata_ids:
        missing_metadata = sorted(matrix_ids - metadata_ids)
        missing_expression = sorted(metadata_ids - matrix_ids)
        raise ExpressionValidationError(
            "Expression/metadata sample IDs do not match "
            f"(missing metadata={missing_metadata[:10]}, missing expression={missing_expression[:10]})."
        )
    metadata = metadata.set_index(sample_id_column, drop=False).loc[matrix.columns]

    numeric = matrix.apply(pd.to_numeric, errors="coerce")
    values = numeric.to_numpy(dtype=np.float64, copy=False)
    if np.isnan(values).any():
        raise ExpressionValidationError("Expression matrix contains missing or non-numeric values.")
    if not np.isfinite(values).all():
        raise ExpressionValidationError("Expression matrix contains infinite values.")

    pattern = IDENTIFIER_PATTERNS.get(species.casefold())
    if pattern is None:
        raise ExpressionValidationError(f"Unsupported species for Ensembl validation: {species!r}.")
    invalid_ids = sorted(gene_id for gene_id in numeric.index if not pattern.fullmatch(gene_id))
    valid_matrix = numeric.loc[[gene_id for gene_id in numeric.index if pattern.fullmatch(gene_id)]]
    if valid_matrix.empty:
        raise ExpressionValidationError(f"No valid {species} Ensembl gene identifiers remain.")

    excluded = set(excluded_samples or ())
    excluded_case_ids = set(excluded_cases or ())
    if case_id_column and excluded_case_ids:
        if case_id_column not in metadata:
            raise ExpressionValidationError(f"Metadata is missing configured patient field {case_id_column!r}.")
        excluded.update(
            metadata.index[metadata[case_id_column].astype(str).isin(excluded_case_ids)].tolist()
        )

    conditions = metadata[condition_column].astype(str).str.strip().str.casefold()
    case_label = case_condition.casefold()
    control_label = control_condition.casefold()
    if case_label == control_label:
        raise ExpressionValidationError("Case and control conditions must be different.")
    included_ids = [sample_id for sample_id in metadata.index if sample_id not in excluded]
    case_samples = [sample_id for sample_id in included_ids if conditions.loc[sample_id] == case_label]
    control_samples = [sample_id for sample_id in included_ids if conditions.loc[sample_id] == control_label]
    if len(case_samples) < minimum_samples_per_group or len(control_samples) < minimum_samples_per_group:
        raise ExpressionValidationError(
            f"Comparison {case_condition!r} vs {control_condition!r} requires at least "
            f"{minimum_samples_per_group} samples per group; found {len(case_samples)} case and "
            f"{len(control_samples)} control samples."
        )

    return ValidatedExpression(
        expression=valid_matrix,
        metadata=metadata,
        case_samples=case_samples,
        control_samples=control_samples,
        excluded_samples=sorted(excluded),
        invalid_gene_ids=invalid_ids,
        duplicate_gene_ids=[],
    )


def validate_raw_counts(counts: pd.DataFrame) -> pd.DataFrame:
    values = counts.to_numpy(dtype=np.float64, copy=False)
    if (values < 0).any():
        raise ExpressionValidationError("Raw count matrix contains negative values.")
    if not np.equal(values, np.floor(values)).all():
        raise ExpressionValidationError(
            "Count-based differential expression requires non-negative integer raw counts; normalized values were supplied."
        )
    if not np.isfinite(values).all():
        raise ExpressionValidationError("Raw count matrix contains infinite values.")
    return counts.astype(np.int64)
