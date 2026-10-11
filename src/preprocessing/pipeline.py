from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd


@dataclass
class PreprocessingSummary:
    dataset_id: str
    species: str
    data_type: str
    n_genes_before: int
    n_genes_after: int
    n_samples_before: int
    n_samples_after: int
    removed_duplicate_genes: int
    removed_low_expression_genes: int
    missing_values_handled: int
    normalized: bool
    log_transformed: bool
    pca_components: int
    hierarchical_clustering: bool
    batch_effects: Dict[str, Any]
    sample_qc: Dict[str, Any]
    gene_qc: Dict[str, Any]
    output_file: str
    log_path: str


def detect_input_data_type(frame: pd.DataFrame) -> str:
    """Infers whether the expression matrix looks like raw counts or already-normalized data."""
    if frame.empty:
        return "unknown"

    numeric = frame.apply(pd.to_numeric, errors="coerce")
    if numeric.isna().all().all():
        return "unknown"

    non_zero = (numeric > 0).sum().sum()
    total = numeric.size
    zero_fraction = 1.0 - (non_zero / total) if total else 0.0
    if numeric.values.max() <= 100 and zero_fraction < 0.6:
        return "normalized"
    if numeric.values.max() > 10000 or numeric.values.min() >= 0:
        return "raw_counts"
    return "normalized"


def _normalize_expression(frame: pd.DataFrame, data_type: str) -> pd.DataFrame:
    working = frame.copy()
    working = working.apply(pd.to_numeric, errors="coerce")
    working = working.replace([np.inf, -np.inf], np.nan)

    if data_type == "raw_counts":
        col_sums = working.sum(axis=0).replace(0, np.nan)
        cpm = working.divide(col_sums, axis=1) * 1_000_000
        working = np.log2(cpm + 1)
        return working

    if data_type == "normalized":
        if working.max().max() > 100:
            working = np.log2(working + 1)
        return working

    return working


def _handle_missing_values(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    working = frame.copy()
    missing_total = int(working.isna().sum().sum())
    if missing_total == 0:
        return working, 0

    if working.shape[0] == 0:
        return working, missing_total

    working = working.fillna(working.median(axis=0))
    return working, missing_total


def _remove_duplicate_genes(frame: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    working = frame.copy()
    before = working.shape[0]
    working = working[~working.index.duplicated(keep="first")]
    return working, before - working.shape[0]


def _remove_low_expression_genes(frame: pd.DataFrame, data_type: str) -> tuple[pd.DataFrame, int]:
    working = frame.copy()
    if working.empty:
        return working, 0

    if data_type == "raw_counts":
        keep_mask = (working > 1).sum(axis=1) >= max(1, min(3, working.shape[1] // 5))
    else:
        keep_mask = (working > 0.1).sum(axis=1) >= max(1, min(3, working.shape[1] // 5))

    removed = int((~keep_mask).sum())
    return working.loc[keep_mask], removed


def _get_batch_effects(frame: pd.DataFrame, metadata_df: Optional[pd.DataFrame]) -> Dict[str, Any]:
    if metadata_df is None or frame.empty:
        return {"detected": False, "method": "none", "reason": "no metadata"}

    meta = metadata_df.copy()
    meta.columns = [str(col).lower() for col in meta.columns]
    batch_col = None
    for candidate in ["batch", "batch_id", "plate", "run", "library_batch"]:
        if candidate in meta.columns:
            batch_col = candidate
            break

    if batch_col is None:
        return {"detected": False, "method": "none", "reason": "batch column missing"}

    sample_ids = frame.columns.astype(str)
    meta_index = meta.copy()
    if "sample_id" in meta_index.columns:
        meta_index = meta_index.set_index("sample_id")
    batch_values = meta_index.loc[meta_index.index.intersection(sample_ids), batch_col]
    if batch_values.empty:
        return {"detected": False, "method": "none", "reason": "no overlapping sample ids"}

    if len(batch_values.unique()) < 2:
        return {"detected": False, "method": "none", "reason": "single batch"}

    return {
        "detected": True,
        "method": "batch_label_projection",
        "n_batches": int(len(batch_values.unique())),
        "batches": batch_values.unique().tolist(),
    }


def _sample_qc(frame: pd.DataFrame) -> Dict[str, Any]:
    if frame.empty:
        return {"passed": True, "removed": [], "reason": "empty dataset"}

    sample_library = frame.sum(axis=0)
    valid = sample_library > 0
    removed = list(sample_library[~valid].index.tolist())
    return {"passed": len(removed) == 0, "removed": removed, "min_library_size": float(sample_library.min()) if not sample_library.empty else 0.0}


def _gene_qc(frame: pd.DataFrame) -> Dict[str, Any]:
    if frame.empty:
        return {"passed": True, "removed": [], "reason": "empty dataset"}

    gene_variance = frame.var(axis=1)
    valid = gene_variance > 0
    removed = list(gene_variance[~valid].index.tolist())
    return {"passed": len(removed) == 0, "removed": removed, "min_variance": float(gene_variance.min()) if not gene_variance.empty else 0.0}


def _pca(frame: pd.DataFrame) -> int:
    if frame.empty or frame.shape[1] < 2:
        return 0

    try:
        from sklearn.decomposition import PCA
        from sklearn.preprocessing import StandardScaler

        X = frame.T.to_numpy()
        scaler = StandardScaler()
        Xs = scaler.fit_transform(X)
        n_components = min(3, Xs.shape[0], Xs.shape[1])
        if n_components < 2:
            return 0
        PCA(n_components=n_components).fit_transform(Xs)
        return n_components
    except Exception:
        return 0


def _hierarchical_clustering(frame: pd.DataFrame) -> bool:
    if frame.empty or frame.shape[1] < 2:
        return False

    try:
        from scipy.cluster.hierarchy import linkage, dendrogram
        from scipy.spatial.distance import pdist

        sample_matrix = frame.T
        distances = pdist(sample_matrix, metric="euclidean")
        linkage(distances, method="average")
        return True
    except Exception:
        return False


def run_preprocessing_pipeline(
    expression: pd.DataFrame,
    metadata_df: Optional[pd.DataFrame],
    dataset_id: str,
    species: str,
    output_dir: str = "data/processed",
) -> Dict[str, Any]:
    """Run the real preprocessing pipeline and persist outputs to disk."""
    working = expression.copy()
    working.index = [str(g).strip() for g in working.index]
    working.columns = [str(s).strip() for s in working.columns]

    before_genes = working.shape[0]
    before_samples = working.shape[1]

    working, duplicate_removed = _remove_duplicate_genes(working)
    data_type = detect_input_data_type(working)
    working = _normalize_expression(working, data_type)
    working, missing_total = _handle_missing_values(working)
    working, low_gene_removed = _remove_low_expression_genes(working, data_type)

    sample_qc = _sample_qc(working)
    if sample_qc["removed"]:
        working = working.drop(columns=sample_qc["removed"], errors="ignore")

    gene_qc = _gene_qc(working)
    if gene_qc["removed"]:
        working = working.drop(index=gene_qc["removed"], errors="ignore")

    batch_effects = _get_batch_effects(working, metadata_df)
    pca_components = _pca(working)
    clustering_ok = _hierarchical_clustering(working)

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    processed_path = output_path / f"{dataset_id}_processed.csv"
    summary_path = output_path / f"{dataset_id}_summary.json"
    log_path = output_path / f"{dataset_id}_preprocessing_log.txt"

    working.to_csv(processed_path)

    summary = PreprocessingSummary(
        dataset_id=dataset_id,
        species=species,
        data_type=data_type,
        n_genes_before=before_genes,
        n_genes_after=working.shape[0],
        n_samples_before=before_samples,
        n_samples_after=working.shape[1],
        removed_duplicate_genes=duplicate_removed,
        removed_low_expression_genes=low_gene_removed,
        missing_values_handled=missing_total,
        normalized=data_type in {"raw_counts", "normalized"},
        log_transformed=data_type in {"raw_counts", "normalized"},
        pca_components=pca_components,
        hierarchical_clustering=clustering_ok,
        batch_effects=batch_effects,
        sample_qc=sample_qc,
        gene_qc=gene_qc,
        output_file=str(processed_path),
        log_path=str(log_path),
    )

    summary_payload = asdict(summary)
    summary_path.write_text(json.dumps(summary_payload, indent=2, default=str), encoding="utf-8")
    log_text = (
        f"Dataset: {dataset_id}\n"
        f"Species: {species}\n"
        f"Input data type: {data_type}\n"
        f"Genes before: {before_genes}\n"
        f"Genes after: {working.shape[0]}\n"
        f"Samples before: {before_samples}\n"
        f"Samples after: {working.shape[1]}\n"
        f"Duplicate genes removed: {duplicate_removed}\n"
        f"Low-expression genes removed: {low_gene_removed}\n"
        f"Missing values handled: {missing_total}\n"
        f"PCA components: {pca_components}\n"
        f"Hierarchical clustering: {clustering_ok}\n"
        f"Batch effects: {json.dumps(batch_effects, default=str)}\n"
        f"Sample QC: {json.dumps(sample_qc, default=str)}\n"
        f"Gene QC: {json.dumps(gene_qc, default=str)}\n"
    )
    log_path.write_text(log_text, encoding="utf-8")

    return summary_payload
