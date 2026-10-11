from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd


PATHOLOGY_FIELDS = (
    "ajcc_pathologic_stage",
    "primary_diagnosis",
    "tumor_grade",
    "morphology",
)
SAMPLE_FIELDS = (
    "sample_id",
    "disease_state",
    "sample_type",
    "case_id",
    "ajcc_pathologic_stage",
    "primary_diagnosis",
    "tumor_grade",
    "morphology",
    "age_at_index_years",
    "sex_at_birth",
    "vital_status",
    "days_to_last_follow_up",
)


def build_phenotype_metadata(
    run_directory: Path,
    repository_root: Path,
    manifest: dict[str, Any],
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    deg_summary_path = run_directory / "deg/human/summary.json"
    if not deg_summary_path.is_file():
        return _empty_outputs("Human DEG sample metadata is unavailable.")
    import json

    deg_summary = json.loads(deg_summary_path.read_text(encoding="utf-8"))
    tumor_sample_ids = set(map(str, deg_summary.get("case_sample_ids", [])))
    control_sample_ids = set(map(str, deg_summary.get("control_sample_ids", [])))
    selected_sample_ids = tumor_sample_ids | control_sample_ids
    datasets = manifest.get("datasets", [])
    if not isinstance(datasets, list):
        return _empty_outputs("The run manifest has no valid dataset list.")
    dataset = next(
        (
            row for row in datasets
            if isinstance(row, dict)
            and str(row.get("species", "")).lower() == "human"
            and row.get("metadata_path")
        ),
        None,
    )
    if dataset is None:
        return _empty_outputs("No human sample metadata source is recorded in the run manifest.")
    metadata_path = Path(str(dataset["metadata_path"])).expanduser().resolve()
    try:
        metadata_path.relative_to(repository_root.resolve())
    except ValueError:
        raise ValueError("The human phenotype metadata path is outside the repository data root.") from None
    if not metadata_path.is_file():
        return _empty_outputs("The human phenotype metadata file recorded in the run manifest is missing.")
    metadata = pd.read_csv(metadata_path, sep="\t", dtype=str, keep_default_na=False)
    required = {"sample_id", "disease_state"}
    if not required.issubset(metadata.columns):
        raise ValueError("Human phenotype metadata must contain sample_id and disease_state.")
    selected = metadata.loc[metadata["sample_id"].astype(str).isin(selected_sample_ids)].copy()
    selected = selected.drop_duplicates("sample_id", keep="first")
    present_fields = [column for column in SAMPLE_FIELDS if column in selected.columns]
    sample_rows = selected[present_fields].copy()
    sample_rows["sample_id"] = sample_rows["sample_id"].astype(str)
    if "disease_state" in sample_rows:
        sample_rows["disease_state"] = sample_rows["disease_state"].replace("", "Not recorded")

    tumor_rows = selected.loc[selected["sample_id"].astype(str).isin(tumor_sample_ids)]
    variable_rows: list[dict[str, Any]] = []
    for field in (*PATHOLOGY_FIELDS, "age_at_index_years", "sex_at_birth", "vital_status"):
        if field not in tumor_rows.columns:
            continue
        values = tumor_rows[field].astype(str).str.strip()
        available = values.ne("") & ~values.str.casefold().isin({
            "not reported", "unknown", "not available", "na", "n/a",
        })
        counts = values.loc[available].value_counts().sort_index()
        variable_rows.append({
            "species": "human",
            "field": field,
            "evidence_type": "CLINICAL_PATHOLOGY_METADATA" if field in PATHOLOGY_FIELDS else "CLINICAL_COVARIATE",
            "tumor_sample_count": int(len(tumor_rows)),
            "observed_sample_count": int(available.sum()),
            "missing_sample_count": int(len(tumor_rows) - available.sum()),
            "category_counts_json": counts.to_json(force_ascii=False),
            "source_accession": str(dataset.get("accession", "")),
            "source_file": str(metadata_path.relative_to(repository_root.resolve())).replace("\\", "/"),
        })
    pathology_observations = sum(
        int(row["observed_sample_count"])
        for row in variable_rows
        if row["field"] in PATHOLOGY_FIELDS
    )
    morphology_summary = {
        "status": "DESCRIPTIVE_METADATA_ONLY" if variable_rows else "UNAVAILABLE",
        "source_accession": str(dataset.get("accession", "")),
        "source_file": str(metadata_path.relative_to(repository_root.resolve())).replace("\\", "/"),
        "selected_human_sample_count": int(sample_rows["sample_id"].nunique()) if "sample_id" in sample_rows else 0,
        "selected_human_tumor_sample_count": int(tumor_rows["sample_id"].nunique()) if "sample_id" in tumor_rows else 0,
        "selected_human_control_sample_count": int(sample_rows["sample_id"].isin(control_sample_ids).sum()) if "sample_id" in sample_rows else 0,
        "observed_pathology_fields": [
            row["field"] for row in variable_rows
            if row["field"] in PATHOLOGY_FIELDS and row["observed_sample_count"] > 0
        ],
        "pathology_field_observations": pathology_observations,
        "image_records": 0,
        "image_derived_features": 0,
        "mouse_pathology_status": "UNAVAILABLE",
        "gene_or_pathway_associations": "NOT_CALCULATED",
        "association_reason": (
            "Clinical pathology fields are linked to only "
            f"{int(tumor_rows['sample_id'].nunique()) if 'sample_id' in tumor_rows else 0} "
            "human tumor samples in this run; no inferential morphology-to-gene association is reported. "
            "No pathology images or validated image-derived features are present."
        ),
        "interpretation": (
            "The morphology field is an ICD-O clinical pathology code, not a measured image feature. "
            "Counts are descriptive only."
        ),
    }
    return (
        sample_rows.reset_index(drop=True),
        pd.DataFrame(variable_rows),
        morphology_summary,
    )


def _empty_outputs(reason: str) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    return (
        pd.DataFrame(columns=SAMPLE_FIELDS),
        pd.DataFrame(columns=[
            "species", "field", "evidence_type", "tumor_sample_count",
            "observed_sample_count", "missing_sample_count", "category_counts_json",
            "source_accession", "source_file",
        ]),
        {
            "status": "UNAVAILABLE",
            "source_accession": None,
            "source_file": None,
            "selected_human_sample_count": 0,
            "selected_human_tumor_sample_count": 0,
            "selected_human_control_sample_count": 0,
            "observed_pathology_fields": [],
            "pathology_field_observations": 0,
            "image_records": 0,
            "image_derived_features": 0,
            "mouse_pathology_status": "UNAVAILABLE",
            "gene_or_pathway_associations": "NOT_CALCULATED",
            "association_reason": reason,
            "interpretation": "No clinical or image-derived morphology findings were inferred.",
        },
    )
