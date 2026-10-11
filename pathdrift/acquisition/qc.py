from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from sklearn.decomposition import PCA


ENSEMBL_PATTERNS = {
    "human": re.compile(r"^ENSG\d+(?:_PAR_Y)?$"),
    "mouse": re.compile(r"^ENSMUSG\d+$"),
}


@dataclass(frozen=True)
class QCConfig:
    min_expression: float = 1.0
    min_samples: int = 3
    max_missing_fraction: float = 0.2
    max_sample_missing_fraction: float = 0.2
    pca_gene_limit: int = 2000
    outlier_z_threshold: float = 3.5
    exclude_outliers: bool = False


def normalize_ensembl_id(value: Any, species: str) -> str | None:
    if pd.isna(value):
        return None
    gene_id = str(value).strip().strip("\"'")
    gene_id = re.sub(r"\.\d+(?=_PAR_Y$|$)", "", gene_id)
    pattern = ENSEMBL_PATTERNS.get(species.lower())
    if pattern is None:
        raise ValueError(f"Unsupported species for Ensembl validation: {species}")
    return gene_id if pattern.fullmatch(gene_id) else None


def _resolve_normalization(data_type: str, configured: str) -> str:
    if configured != "auto":
        allowed = {"log2cpm", "log2", "none"}
        if configured not in allowed:
            raise ValueError(f"Unsupported normalization method: {configured}")
        if data_type == "raw_counts" and configured == "none":
            raise ValueError("Raw RNA-seq counts require a normalization method")
        return configured
    if data_type == "raw_counts":
        return "log2cpm"
    if data_type in {"tpm", "fpkm"}:
        return "log2"
    if data_type in {"normalized", "microarray"}:
        return "none"
    raise ValueError(f"Cannot select normalization for undeclared data type: {data_type}")


def run_quality_control(
    expression: pd.DataFrame,
    metadata: pd.DataFrame,
    *,
    species: str,
    data_type: str,
    config: QCConfig | None = None,
    normalization_method: str = "auto",
    gene_identifier_type: str = "ensembl",
) -> dict[str, Any]:
    """Validate, filter, normalize, and calculate sample-level QC from a real matrix."""
    config = config or QCConfig()
    if gene_identifier_type not in {"ensembl", "source"}:
        raise ValueError(f"Unsupported gene identifier type: {gene_identifier_type}")
    if expression.empty or expression.shape[1] < 3:
        raise ValueError("Expression matrix must contain gene IDs and at least two samples")
    if "gene_id" not in expression.columns:
        raise ValueError("Expression matrix must include a gene_id column")
    if "sample_id" not in metadata.columns:
        raise ValueError("Sample metadata must include sample_id")

    source_sample_ids = [str(column) for column in expression.columns if column != "gene_id"]
    if len(source_sample_ids) < 2:
        raise ValueError("At least two expression samples are required for QC")
    if len(source_sample_ids) != len(set(source_sample_ids)):
        raise ValueError("Expression matrix contains duplicate sample columns")

    metadata = metadata.copy()
    metadata["sample_id"] = metadata["sample_id"].astype(str)
    if metadata["sample_id"].duplicated().any():
        duplicates = sorted(metadata.loc[metadata["sample_id"].duplicated(False), "sample_id"].unique())
        raise ValueError(f"Sample metadata contains duplicate sample IDs: {duplicates[:10]}")
    missing_metadata = sorted(set(source_sample_ids) - set(metadata["sample_id"]))
    if missing_metadata:
        raise ValueError(f"Expression samples lack metadata: {missing_metadata[:10]}")

    initial_samples = len(source_sample_ids)
    initial_genes = int(expression.shape[0])
    if gene_identifier_type == "ensembl":
        gene_ids = expression["gene_id"].map(lambda value: normalize_ensembl_id(value, species))
    else:
        gene_ids = expression["gene_id"].map(
            lambda value: None if pd.isna(value) else str(value).strip().strip("\"'") or None
        )
    valid_mask = gene_ids.notna()
    invalid_gene_count = int((~valid_mask).sum())
    matrix = expression.loc[valid_mask, source_sample_ids].copy()
    matrix.index = gene_ids.loc[valid_mask].astype(str)
    matrix.columns = source_sample_ids
    numeric = matrix.apply(pd.to_numeric, errors="coerce").replace([np.inf, -np.inf], np.nan)
    non_numeric_cells = int(numeric.isna().sum().sum()) - int(matrix.isna().sum().sum())
    duplicate_gene_rows = int(numeric.index.duplicated(keep=False).sum())

    if data_type == "raw_counts" and numeric.lt(0).any().any():
        raise ValueError("Raw count data contains negative values")
    aggregation = "sum" if data_type == "raw_counts" else "mean"
    duplicate_gene_ids = int(numeric.index.duplicated().sum())
    if duplicate_gene_ids:
        numeric = numeric.groupby(level=0, sort=False).agg(aggregation)

    original_numeric = numeric.copy()
    sample_missing = original_numeric.isna().mean(axis=0)
    sample_zero = original_numeric.eq(0).mean(axis=0)
    total_expression = original_numeric.sum(axis=0, min_count=1)
    library_size = total_expression if data_type == "raw_counts" else pd.Series(np.nan, index=source_sample_ids)
    sample_exclusion_reasons: dict[str, str] = {}
    for sample_id, fraction in sample_missing.items():
        if float(fraction) > config.max_sample_missing_fraction:
            sample_exclusion_reasons[str(sample_id)] = "sample missing fraction exceeded configured maximum"
    for sample_id, size in total_expression.items():
        if pd.isna(size) or float(size) <= 0:
            sample_exclusion_reasons[str(sample_id)] = "zero or unavailable library size"

    usable_samples = [sample_id for sample_id in source_sample_ids if sample_id not in sample_exclusion_reasons]
    if len(usable_samples) < 2:
        raise ValueError("Fewer than two samples remain after configured file-quality checks")
    numeric = original_numeric[usable_samples]

    gene_missing = numeric.isna().mean(axis=1)
    expression_filter = numeric.ge(config.min_expression).sum(axis=1) >= config.min_samples
    retain_gene = gene_missing.le(config.max_missing_fraction) & expression_filter
    filtered = numeric.loc[retain_gene]
    if filtered.empty:
        raise ValueError("No genes remain after configured expression and missingness filters")
    excluded_genes = int(len(numeric) - len(filtered))
    missing_cells_after_filter = int(filtered.isna().sum().sum())
    filtered = filtered.T.fillna(filtered.median(axis=1)).T

    selected_normalization = _resolve_normalization(data_type, normalization_method)
    if selected_normalization == "log2cpm":
        sizes = filtered.sum(axis=0)
        if (sizes <= 0).any():
            raise ValueError("Cannot calculate CPM for a zero-size library")
        normalized = np.log2(filtered.divide(sizes, axis=1) * 1_000_000 + 1)
    elif selected_normalization == "log2":
        if (filtered < 0).any().any():
            raise ValueError("Log2 normalization requires non-negative expression values")
        normalized = np.log2(filtered + 1)
    else:
        normalized = filtered.astype(float)

    variance = normalized.var(axis=1, ddof=1).replace([np.inf, -np.inf], np.nan).fillna(0)
    variable_genes = variance.nlargest(min(config.pca_gene_limit, int((variance > 0).sum()))).index
    if len(variable_genes) < 2:
        raise ValueError("PCA requires at least two variable genes")
    pca_input = normalized.loc[variable_genes].T.to_numpy(dtype=np.float64)
    component_count = min(3, len(usable_samples) - 1, pca_input.shape[1])
    pca_model = PCA(n_components=component_count, svd_solver="full")
    transformed = pca_model.fit_transform(pca_input)
    pca_columns = [f"PC{index + 1}" for index in range(component_count)]
    pca_coordinates = pd.DataFrame(transformed, index=usable_samples, columns=pca_columns)

    if component_count:
        scaled = pca_coordinates.to_numpy()
        scales = scaled.std(axis=0, ddof=1)
        scales[scales == 0] = 1
        distances = np.sqrt(np.square((scaled - scaled.mean(axis=0)) / scales).sum(axis=1))
    else:
        distances = np.zeros(len(usable_samples))
    distance_median = float(np.median(distances))
    mad = float(np.median(np.abs(distances - distance_median)))
    if mad == 0:
        distance_sd = float(np.std(distances, ddof=1)) if len(distances) > 1 else 0.0
        outlier_scores = np.zeros(len(distances)) if distance_sd == 0 else (distances - distance_median) / distance_sd
    else:
        outlier_scores = 0.6745 * (distances - distance_median) / mad
    outlier_score_by_sample = dict(zip(usable_samples, outlier_scores.tolist()))
    flagged = np.abs(outlier_scores) > config.outlier_z_threshold
    outlier_decisions = {
        sample_id: {
            "sample_id": sample_id,
            "reason": "robust distance from the sample PCA centroid",
            "metric": float(score),
            "threshold": config.outlier_z_threshold,
            "decision": "excluded" if config.exclude_outliers else "flagged_retained",
        }
        for sample_id, score, is_flagged in zip(usable_samples, outlier_scores, flagged)
        if is_flagged
    }
    if config.exclude_outliers:
        usable_samples = [sample_id for sample_id in usable_samples if sample_id not in outlier_decisions]
        if len(usable_samples) < 2:
            raise ValueError("Outlier exclusion would leave fewer than two samples")
        normalized = normalized[usable_samples]
        pca_coordinates = pca_coordinates.loc[usable_samples]

    metadata_by_sample = metadata.set_index("sample_id")
    sample_qc = []
    for sample_id in source_sample_ids:
        sample_metadata = metadata_by_sample.loc[sample_id].to_dict()
        row: dict[str, Any] = {
            "sample_id": sample_id,
            "library_size": float(library_size[sample_id]) if pd.notna(library_size[sample_id]) else None,
            "detected_genes": int(original_numeric[sample_id].gt(0).sum()),
            "missing_fraction": float(sample_missing[sample_id]),
            "zero_fraction": float(sample_zero[sample_id]),
            "mean_expression": float(normalized[sample_id].mean()) if sample_id in normalized else None,
            "median_expression": float(normalized[sample_id].median()) if sample_id in normalized else None,
            "outlier_score": float(outlier_score_by_sample[sample_id]) if sample_id in outlier_score_by_sample else None,
            "is_outlier": bool(sample_id in outlier_decisions),
            "pca_coordinates": pca_coordinates.loc[sample_id].to_dict() if sample_id in pca_coordinates.index else {},
            "cluster": None,
            "disease_state": str(sample_metadata.get("disease_state") or "unknown"),
            "excluded": sample_id in sample_exclusion_reasons or (config.exclude_outliers and sample_id in outlier_decisions),
            "exclusion_reason": sample_exclusion_reasons.get(sample_id) or (outlier_decisions.get(sample_id, {}).get("reason") if config.exclude_outliers else None),
        }
        sample_qc.append(row)

    if len(usable_samples) >= 2:
        sample_distance = normalized.corr(method="pearson").fillna(0)
        correlation = sample_distance
        cluster_tree = linkage(normalized.T.to_numpy(dtype=float), method="average", metric="correlation")
        cluster_labels = fcluster(cluster_tree, t=min(3, len(usable_samples)), criterion="maxclust")
        cluster_by_sample = dict(zip(usable_samples, cluster_labels.tolist()))
        for row in sample_qc:
            row["cluster"] = int(cluster_by_sample[row["sample_id"]]) if row["sample_id"] in cluster_by_sample else None
    else:
        raise ValueError("Correlation and clustering require at least two retained samples")

    for row in sample_qc:
        row["batch_metadata"] = {
            key: str(metadata_by_sample.loc[row["sample_id"], key])
            for key in ("batch", "plate", "center", "platform", "study", "processing_batch")
            if key in metadata.columns and pd.notna(metadata_by_sample.loc[row["sample_id"], key])
        }

    batch_variables = []
    for key in ("batch", "plate", "center", "platform", "study", "processing_batch"):
        if key in metadata.columns:
            values = metadata_by_sample.loc[usable_samples, key].dropna().astype(str)
            if not values.empty:
                levels = sorted(values.unique().tolist())
                batch_variables.append({
                    "variable": key,
                    "levels": levels,
                    "level_count": len(levels),
                    "varies": len(levels) > 1,
                })

    summary = {
        "initial_samples": initial_samples,
        "retained_samples": len(usable_samples),
        "initial_genes": initial_genes,
        "validated_ensembl_genes": int(len(numeric)) if gene_identifier_type == "ensembl" else None,
        "validated_gene_ids": int(len(numeric)),
        "gene_identifier_type": gene_identifier_type,
        "retained_genes": int(normalized.shape[0]),
        "excluded_samples": sorted(set(sample_exclusion_reasons) | (set(outlier_decisions) if config.exclude_outliers else set())),
        "excluded_genes": excluded_genes + invalid_gene_count,
        "invalid_gene_ids": invalid_gene_count,
        "duplicate_gene_rows": duplicate_gene_rows,
        "duplicate_gene_ids_aggregated": duplicate_gene_ids,
        "non_numeric_cells": non_numeric_cells,
        "missing_cells_imputed": missing_cells_after_filter,
        "outliers": list(outlier_decisions.values()),
        "batch_variables": batch_variables,
        "normalization_method": selected_normalization,
        "normalization_data_type": data_type,
        "configuration": asdict(config),
    }
    return {
        "normalized_expression": normalized,
        "sample_qc": pd.DataFrame(sample_qc),
        "pca_coordinates": pca_coordinates,
        "sample_correlation": correlation,
        "sample_clustering": pd.DataFrame({"sample_id": usable_samples, "cluster": [cluster_by_sample[sample_id] for sample_id in usable_samples]}),
        "summary": summary,
    }


def write_qc_outputs(result: dict[str, Any], output_dir: str | Path) -> dict[str, str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import seaborn as sns
    from scipy.cluster.hierarchy import dendrogram

    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    result["sample_qc"].to_csv(target / "sample_qc.csv", index=False)
    result["pca_coordinates"].rename_axis("sample_id").to_csv(target / "pca_coordinates.csv")
    result["sample_correlation"].to_csv(target / "sample_correlation.csv")
    result["sample_clustering"].to_csv(target / "sample_clustering.csv", index=False)
    (target / "summary.json").write_text(json.dumps(result["summary"], indent=2, default=str), encoding="utf-8")

    coordinates = result["pca_coordinates"]
    sample_qc = result["sample_qc"].set_index("sample_id")
    fig, axis = plt.subplots(figsize=(8, 6))
    for label in sorted(sample_qc.loc[coordinates.index, "disease_state"].astype(str).unique()):
        sample_ids = sample_qc.index[sample_qc["disease_state"].astype(str) == label].intersection(coordinates.index)
        axis.scatter(coordinates.loc[sample_ids, "PC1"], coordinates.loc[sample_ids, "PC2"], label=label, alpha=0.85)
        for sample_id in sample_ids:
            axis.annotate(sample_id, (coordinates.loc[sample_id, "PC1"], coordinates.loc[sample_id, "PC2"]), fontsize=6, alpha=0.7)
    axis.set(xlabel="PC1", ylabel="PC2", title="Sample PCA")
    if sample_qc.loc[coordinates.index, "disease_state"].nunique() > 1:
        axis.legend(fontsize=8)
    fig.tight_layout()
    fig.savefig(target / "pca.png", dpi=160)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(max(7, len(coordinates) * 0.32), max(6, len(coordinates) * 0.28)))
    sns.heatmap(result["sample_correlation"], cmap="vlag", vmin=-1, vmax=1, square=True, ax=axis)
    axis.set_title("Sample Pearson correlation")
    fig.tight_layout()
    fig.savefig(target / "sample_correlation.png", dpi=160)
    plt.close(fig)

    values = result["normalized_expression"].T.to_numpy(dtype=float)
    tree = linkage(values, method="average", metric="correlation")
    fig, axis = plt.subplots(figsize=(max(8, len(coordinates) * 0.35), 6))
    dendrogram(tree, labels=coordinates.index.tolist(), leaf_rotation=90, ax=axis)
    axis.set_title("Hierarchical sample clustering")
    axis.set_ylabel("Correlation distance")
    fig.tight_layout()
    fig.savefig(target / "sample_clustering.png", dpi=160)
    plt.close(fig)

    return {"qc_dir": str(target.resolve())}