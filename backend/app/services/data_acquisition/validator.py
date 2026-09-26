from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd


def validate_metadata_file(path: str) -> Dict[str, Any]:
    file_path = Path(path)
    if not file_path.exists():
        return {"valid": False, "errors": ["Metadata file does not exist."], "warnings": []}
    if file_path.stat().st_size == 0:
        return {"valid": False, "errors": ["Metadata file is empty."], "warnings": []}
    return {"valid": True, "errors": [], "warnings": []}


def validate_expression_matrix(path: str) -> Dict[str, Any]:
    file_path = Path(path)
    errors: List[str] = []
    warnings: List[str] = []

    if not file_path.exists():
        return {"valid": False, "errors": ["Expression file does not exist."], "warnings": []}
    if file_path.stat().st_size == 0:
        return {"valid": False, "errors": ["Expression file is empty."], "warnings": []}

    try:
        frame = pd.read_csv(file_path)
    except Exception as exc:  # pragma: no cover - defensive path
        return {"valid": False, "errors": [f"Unable to parse expression matrix: {exc}"], "warnings": []}

    if frame.empty:
        errors.append("Expression matrix is empty.")

    expected_columns = ["gene_id", "gene_symbol"]
    missing = [column for column in expected_columns if column not in frame.columns]
    if missing and "gene_id" not in frame.columns:
        errors.append(f"Missing gene identifier columns: {missing}")

    if "gene_id" in frame.columns and frame["gene_id"].isnull().any():
        errors.append("Gene identifiers contain null values.")

    if frame.shape[1] < 2:
        errors.append("Expression matrix has fewer than two columns.")

    if frame.shape[0] < 1:
        errors.append("Expression matrix has no rows.")

    numeric_cols = [column for column in frame.columns if column != "gene_id" and column != "gene_symbol"]
    if numeric_cols:
        numeric_frame = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
        bad_cells = int(numeric_frame.isna().sum().sum())
        if bad_cells:
            warnings.append(f"Detected {bad_cells} non-numeric expression values; they will be treated as missing.")

    duplicates = frame["gene_id"].duplicated().sum() if "gene_id" in frame.columns else 0
    if duplicates:
        warnings.append(f"Found {duplicates} duplicate gene identifiers.")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "n_rows": int(frame.shape[0]),
        "n_columns": int(frame.shape[1]),
        "duplicate_genes": int(duplicates),
    }
