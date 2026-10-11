from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .downloader import sha256_file
from .metadata import read_sample_metadata


def load_expression_matrix(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError(f"Expression matrix is missing or empty: {source}")
    suffixes = [suffix.lower() for suffix in source.suffixes]
    if ".parquet" in suffixes:
        frame = pd.read_parquet(source)
        if "gene_id" not in frame.columns:
            frame = frame.rename_axis("gene_id").reset_index()
    else:
        separator = "\t" if any(suffix in suffixes for suffix in (".tsv", ".txt")) else ","
        frame = pd.read_csv(source, sep=separator, compression="infer", low_memory=False)
    if frame.empty:
        raise ValueError(f"Expression matrix has no records: {source}")
    if "gene_id" not in frame.columns:
        raise ValueError(f"Expression matrix lacks a gene_id column: {source}")
    if frame.columns.duplicated().any():
        duplicates = frame.columns[frame.columns.duplicated()].astype(str).tolist()
        raise ValueError(f"Expression matrix has duplicate columns: {duplicates[:10]}")
    sample_columns = [column for column in frame.columns if column not in {"gene_id", "gene_symbol"}]
    if len(sample_columns) < 2:
        raise ValueError("Expression matrix needs at least two sample columns")
    if frame["gene_id"].isna().any() or frame["gene_id"].astype(str).str.strip().eq("").any():
        raise ValueError("Expression matrix contains empty gene identifiers")
    for column in sample_columns:
        converted = pd.to_numeric(frame[column], errors="coerce")
        invalid = int(converted.isna().sum()) - int(frame[column].isna().sum())
        if invalid:
            raise ValueError(f"Expression matrix contains {invalid} non-numeric values in sample {column}")
        frame[column] = converted
    return frame


def validate_dataset_files(
    expression_path: str | Path,
    metadata_path: str | Path,
    *,
    expected_expression_sha256: str | None = None,
    expected_metadata_sha256: str | None = None,
) -> dict[str, Any]:
    expression_file = Path(expression_path)
    metadata_file = Path(metadata_path)
    if not metadata_file.is_file() or metadata_file.stat().st_size == 0:
        raise ValueError(f"Sample metadata is missing or empty: {metadata_file}")
    expression_sha256 = sha256_file(expression_file)
    metadata_sha256 = sha256_file(metadata_file)
    if expected_expression_sha256 and expression_sha256 != expected_expression_sha256.lower():
        raise ValueError(f"Expression checksum mismatch: {expression_file}")
    if expected_metadata_sha256 and metadata_sha256 != expected_metadata_sha256.lower():
        raise ValueError(f"Metadata checksum mismatch: {metadata_file}")

    expression = load_expression_matrix(expression_file)
    metadata = read_sample_metadata(metadata_file)
    sample_ids = [str(column) for column in expression.columns if column not in {"gene_id", "gene_symbol"}]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Expression matrix contains duplicate sample identifiers")
    metadata_ids = set(metadata["sample_id"])
    missing_metadata = sorted(set(sample_ids) - metadata_ids)
    if missing_metadata:
        raise ValueError(f"Expression samples lack metadata: {missing_metadata[:10]}")
    if "disease_state" not in metadata.columns:
        raise ValueError("Sample metadata must include disease_state")

    return {
        "expression": expression,
        "metadata": metadata.set_index("sample_id").loc[sample_ids].reset_index(),
        "expression_sha256": expression_sha256,
        "metadata_sha256": metadata_sha256,
        "expression_bytes": expression_file.stat().st_size,
        "metadata_bytes": metadata_file.stat().st_size,
        "gene_rows": int(expression.shape[0]),
        "sample_columns": len(sample_ids),
        "metadata_samples": len(metadata),
        "duplicate_gene_ids": int(expression["gene_id"].astype(str).duplicated().sum()),
        "invalid_numeric_cells": 0,
    }