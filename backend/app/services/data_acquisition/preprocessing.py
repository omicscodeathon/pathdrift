from __future__ import annotations

import re
from typing import Dict, List, Tuple

import pandas as pd


def normalize_gene_ids(series: pd.Series) -> pd.Series:
    normalized = []
    for value in series:
        if pd.isna(value):
            normalized.append(value)
            continue
        gene_id = str(value).strip()
        gene_id = re.sub(r"^(ENS(?:G|MUSG)\d+)\.\d+(?=_PAR_Y$|$)", r"\1", gene_id)
        gene_id = gene_id.replace('"', '').replace("'", "")
        normalized.append(gene_id)
    return pd.Series(normalized, index=series.index)


def preprocess_expression_matrix(frame: pd.DataFrame) -> Tuple[pd.DataFrame, Dict[str, object]]:
    working = frame.copy()
    if "gene_id" in working.columns:
        working["gene_id"] = normalize_gene_ids(working["gene_id"])

    working = working.drop_duplicates(subset=["gene_id"], keep="first") if "gene_id" in working.columns else working
    working = working.replace([float("inf"), float("-inf")], pd.NA)
    numeric_columns = [column for column in working.columns if column not in {"gene_id", "gene_symbol"}]
    if numeric_columns:
        working[numeric_columns] = working[numeric_columns].apply(pd.to_numeric, errors="coerce")
        working[numeric_columns] = working[numeric_columns].fillna(0)

    summary = {
        "n_genes_after": int(working.shape[0]),
        "n_samples_after": int(working.shape[1] - (1 if "gene_id" in working.columns else 0)),
        "normalized_gene_ids": bool("gene_id" in working.columns),
        "duplicate_genes_removed": bool("gene_id" in working.columns and working["gene_id"].duplicated().sum() > 0),
    }
    return working, summary
