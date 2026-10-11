from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from ..acquisition.registry import ROOT


@dataclass
class LabeledExpression:
    run_id: str
    accession: str
    species: str
    features: pd.DataFrame
    labels: pd.Series
    groups: pd.Series | None
    sample_metadata: pd.DataFrame
    expression_path: Path
    metadata_path: Path
    preprocessing: dict[str, Any]


def _run_directory(run_id: str) -> Path:
    if len(run_id) != 36 or any(c not in "0123456789abcdefABCDEF-" for c in run_id):
        raise ValueError("run_id must be a UUID.")
    run_root = (ROOT / "results" / "runs").resolve()
    run_directory = (run_root / run_id).resolve()
    try:
        run_directory.relative_to(run_root)
    except ValueError as exc:
        raise ValueError("The requested run path is invalid.") from exc
    return run_directory


def _manifest(run_id: str) -> tuple[Path, dict[str, Any]]:
    run_directory = _run_directory(run_id)
    manifest_path = run_directory / "manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Saved analysis manifest is missing for run {run_id}.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict) or manifest.get("run_id") != run_id:
        raise ValueError(f"Saved analysis manifest does not match run {run_id}.")
    return run_directory, manifest


def _resolve_input_path(value: str | None, *, run_id: str, expected_name: str) -> Path:
    if value:
        declared = Path(value)
        if not declared.is_absolute():
            declared = ROOT / declared
        if declared.is_file():
            resolved = declared.resolve()
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError as exc:
                raise ValueError("Manifest input paths must remain inside the project workspace.") from exc
            return resolved

    candidates = list((ROOT / "data" / "processed").glob(f"*/{run_id}/{expected_name}"))
    candidates = [path.resolve() for path in candidates if path.is_file()]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError(
            f"Multiple processed matrices match run {run_id} and {expected_name}; "
            "refusing to guess which source is authoritative."
        )
    raise FileNotFoundError(
        f"Processed input {expected_name} is missing for run {run_id}."
    )


def summarize_labeled_cohorts(run_id: str, species: str) -> list[dict[str, Any]]:
    _, manifest = _manifest(run_id)
    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("Run manifest has no valid datasets list.")

    summaries = []
    for entry in datasets:
        if (
            not isinstance(entry, dict)
            or str(entry.get("species", "")).lower() != species.lower()
            or not entry.get("metadata_path")
            or not entry.get("accession")
        ):
            continue
        metadata_path = Path(str(entry["metadata_path"]))
        if not metadata_path.is_absolute():
            metadata_path = ROOT / metadata_path
        metadata_path = metadata_path.resolve()
        try:
            metadata_path.relative_to(ROOT.resolve())
        except ValueError as exc:
            raise ValueError(
                "Manifest input paths must remain inside the project workspace."
            ) from exc
        if not metadata_path.is_file():
            raise FileNotFoundError(f"Sample metadata is missing: {metadata_path}")
        metadata = pd.read_csv(metadata_path, sep="\t", compression="infer")
        if "disease_state" not in metadata:
            raise ValueError(
                f"Metadata for {entry['accession']} has no disease_state column."
            )
        labels = metadata["disease_state"].astype(str).str.strip().str.lower()
        counts = labels.value_counts()
        summaries.append({
            "accession": str(entry["accession"]),
            "tissue": entry.get("tissue"),
            "total_samples": int(len(metadata)),
            "healthy_samples": int(counts.get("healthy", 0)),
            "cancer_samples": int(counts.get("cancer", 0)),
            "other_label_samples": int(len(metadata) - counts.get("healthy", 0) - counts.get("cancer", 0)),
            "reference_role": entry.get("reference_role"),
        })
    return summaries


def load_labeled_expression(run_id: str, species: str = "human") -> LabeledExpression:
    _, manifest = _manifest(run_id)
    phase3 = manifest.get("phase3")
    if (
        str(manifest.get("status", "")).upper() != "COMPLETED"
        or not isinstance(phase3, dict)
        or str(phase3.get("status", "")).upper() != "COMPLETED"
    ):
        raise ValueError(f"Run {run_id} does not have a completed Phase 3 manifest.")

    datasets = manifest.get("datasets")
    if not isinstance(datasets, list):
        raise ValueError("Run manifest has no valid datasets list.")
    eligible = [
        entry for entry in datasets
        if isinstance(entry, dict)
        and str(entry.get("species", "")).lower() == species.lower()
        and entry.get("metadata_path")
        and entry.get("processed_path")
        and entry.get("accession")
    ]
    if len(eligible) != 1:
        raise ValueError(
            f"Expected exactly one labeled {species} expression dataset in run {run_id}; "
            f"found {len(eligible)}. Cross-study pooling is not performed."
        )
    entry = eligible[0]
    accession = str(entry["accession"])
    expression_path = _resolve_input_path(
        entry.get("processed_path"),
        run_id=run_id,
        expected_name=Path(str(entry["processed_path"])).name,
    )
    metadata_path = Path(str(entry["metadata_path"]))
    if not metadata_path.is_absolute():
        metadata_path = ROOT / metadata_path
    metadata_path = metadata_path.resolve()
    try:
        metadata_path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ValueError("Manifest input paths must remain inside the project workspace.") from exc
    if not metadata_path.is_file():
        raise FileNotFoundError(f"Sample metadata is missing: {metadata_path}")

    if expression_path.suffix.lower() == ".parquet":
        matrix = pd.read_parquet(expression_path)
    elif expression_path.suffix.lower() in {".gz", ".tsv", ".csv"}:
        separator = "," if expression_path.suffix.lower() == ".csv" else "\t"
        matrix = pd.read_csv(expression_path, sep=separator, compression="infer", index_col=0)
    else:
        raise ValueError(f"Unsupported expression format: {expression_path.suffix}")

    metadata = pd.read_csv(metadata_path, sep="\t", compression="infer")
    metadata_row_count = len(metadata)
    required = {"sample_id", "disease_state"}
    if not required.issubset(metadata.columns):
        raise ValueError(f"Metadata must contain columns: {', '.join(sorted(required))}.")
    if matrix.columns.has_duplicates:
        raise ValueError(f"Expression matrix for {accession} contains duplicate sample IDs.")
    duplicate_metadata = metadata["sample_id"].duplicated(keep=False)
    if duplicate_metadata.any():
        duplicates = metadata.loc[duplicate_metadata, "sample_id"].astype(str).unique().tolist()
        raise ValueError(
            "Sample metadata contains duplicate sample IDs; resolve the ambiguous labels before "
            f"training. Duplicate IDs: {', '.join(duplicates[:10])}"
        )
    metadata = metadata.copy()
    metadata["disease_state"] = metadata["disease_state"].astype(str).str.strip().str.lower()
    valid_labels = metadata["disease_state"].isin({"healthy", "cancer"})
    unsupported_label_samples = metadata.loc[~valid_labels, "sample_id"].astype(str).tolist()
    unlabeled_samples = metadata.loc[
        metadata["disease_state"].isin({"", "nan", "none", "na", "unknown"}),
        "sample_id",
    ].astype(str).tolist()
    labeled_metadata = metadata.loc[valid_labels].copy()
    sample_ids = [
        sample for sample in labeled_metadata["sample_id"].astype(str)
        if sample in matrix.columns
    ]
    unmatched_labeled_samples = [
        sample for sample in labeled_metadata["sample_id"].astype(str)
        if sample not in matrix.columns
    ]
    if not sample_ids:
        raise ValueError(f"No metadata sample IDs match the {accession} expression matrix.")

    metadata = labeled_metadata.set_index("sample_id").loc[sample_ids].reset_index()
    features = matrix.loc[:, sample_ids].T
    features.index = pd.Index(sample_ids, name="sample_id")
    features.columns = features.columns.astype(str)
    if features.columns.has_duplicates:
        raise ValueError(f"Expression matrix for {accession} contains duplicate gene identifiers.")
    features = features.apply(pd.to_numeric, errors="coerce")
    if features.empty or features.shape[1] == 0:
        raise ValueError("The matched expression matrix contains no usable features.")
    missing_cells = int(features.isna().sum().sum())
    all_missing_features = int(features.isna().all(axis=0).sum())
    constant_features = int(features.nunique(dropna=True).le(1).sum())
    labels = metadata.set_index("sample_id").loc[sample_ids, "disease_state"].map(
        {"healthy": 0, "cancer": 1}
    ).astype(int)

    group_column = next(
        (column for column in ("case_id", "patient_id", "subject_id") if column in metadata.columns),
        None,
    )
    groups = None
    if group_column:
        group_values = metadata.set_index("sample_id").loc[sample_ids, group_column]
        if group_values.notna().all() and group_values.nunique() < len(group_values):
            groups = group_values.astype(str)

    preprocessing = {
        "metadata_rows": int(metadata_row_count),
        "matched_labeled_samples": int(len(sample_ids)),
        "unlabeled_samples_excluded": int(len(unlabeled_samples)),
        "unsupported_label_samples_excluded": int(len(unsupported_label_samples) - len(unlabeled_samples)),
        "labeled_samples_missing_from_expression": int(len(unmatched_labeled_samples)),
        "duplicate_metadata_sample_ids": 0,
        "duplicate_expression_gene_ids": 0,
        "missing_expression_cells": missing_cells,
        "all_missing_features_before_fold_imputation": all_missing_features,
        "constant_features_before_fold_filtering": constant_features,
        "missing_values": "Median imputation is fitted separately inside each training fold.",
        "constant_features": "Zero-variance filtering is fitted separately inside each training fold.",
        "feature_selection": "ANOVA F-score top-100 selection is fitted separately inside each training fold.",
        "scaling": "Standard scaling is fitted separately inside each training fold.",
        "label_mapping": {"healthy": 0, "cancer": 1},
        "excluded_sample_ids": (unlabeled_samples + unmatched_labeled_samples)[:100],
    }
    return LabeledExpression(
        run_id=run_id,
        accession=accession,
        species=species.lower(),
        features=features,
        labels=labels,
        groups=groups,
        sample_metadata=metadata,
        expression_path=expression_path,
        metadata_path=metadata_path,
        preprocessing=preprocessing,
    )
