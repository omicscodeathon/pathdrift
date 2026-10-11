from __future__ import annotations

import math
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker


ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "backend"
sys.path.insert(0, str(BACKEND_ROOT))


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    from app.core.config import settings

    engine = create_engine(settings.DATABASE_URL_SYNC, pool_pre_ping=True)
    return sessionmaker(bind=engine, expire_on_commit=False)


def open_session() -> Session:
    return _session_factory()()


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if hasattr(value, "item"):
        return json_safe(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if pd.isna(value):
        return None
    return value


def resolve_project(session: Session, project_name: str, owner_username: str):
    from app.models import Project, User

    project = session.execute(
        select(Project)
        .join(User, User.id == Project.owner_id)
        .where(Project.name == project_name, User.username == owner_username)
    ).scalar_one_or_none()
    if project is None:
        raise ValueError(
            f"Configured project {project_name!r} for owner {owner_username!r} was not found"
        )
    return project


def create_run(session: Session, project_id: str, config: dict[str, Any], run_id: str):
    from app.models import AnalysisRun

    run = AnalysisRun(id=run_id, project_id=project_id, status="PENDING", stage="PENDING", config=json_safe(config))
    session.add(run)
    session.flush()
    return run


def set_run_state(
    session: Session,
    run,
    status: str,
    *,
    error_message: str | None = None,
    completed_at: datetime | None = None,
) -> None:
    run.status = status
    run.stage = status
    run.error_message = error_message
    if status == "RUNNING" and run.started_at is None:
        run.started_at = datetime.now(timezone.utc)
    if completed_at:
        run.completed_at = completed_at
    session.commit()


def register_dataset(
    session: Session,
    run,
    project,
    *,
    accession: str,
    name: str,
    source: str,
    species: str,
    tissue: str,
    platform: str | None,
    data_type: str,
    version: str | None,
    expression_path: str,
    metadata_path: str,
    raw_expression_path: str,
    checksum: str,
    download_date: datetime,
    retrieval_url: str,
    processing_steps: dict[str, Any],
    provenance: dict[str, Any],
    metadata: pd.DataFrame,
    qc_result: dict[str, Any],
):
    from app.models import (
        AnalysisRunDataset,
        DataTypeEnum,
        Dataset,
        DiseaseStateEnum,
        Sample,
        SpeciesEnum,
        SampleQC,
    )

    species_value = SpeciesEnum(species.lower())
    data_type_value = {
        "raw_counts": DataTypeEnum.RAW_COUNTS,
        "tpm": DataTypeEnum.NORMALIZED,
        "fpkm": DataTypeEnum.NORMALIZED,
        "normalized": DataTypeEnum.NORMALIZED,
        "microarray": DataTypeEnum.MICROARRAY,
    }.get(data_type.lower())
    if data_type_value is None:
        raise ValueError(f"Unsupported dataset data type: {data_type}")

    dataset = session.execute(
        select(Dataset).where(Dataset.project_id == project.id, Dataset.accession == accession)
    ).scalar_one_or_none()
    if dataset is None:
        dataset = Dataset(
            project_id=project.id,
            owner_id=project.owner_id,
            name=name,
            species=species_value,
            accession=accession,
        )
        session.add(dataset)
        session.flush()

    dataset.name = name
    dataset.description = f"Verified {source} expression dataset {accession}; no identifiers were inferred from symbols."
    dataset.species = species_value
    dataset.tissue = tissue
    dataset.source = source
    dataset.platform = platform
    dataset.data_type = data_type_value
    dataset.expression_file_path = expression_path
    dataset.metadata_file_path = metadata_path
    dataset.n_genes = int(qc_result["summary"]["retained_genes"])
    dataset.n_samples = int(qc_result["summary"]["retained_samples"])
    dataset.n_healthy = int(metadata["disease_state"].str.casefold().isin({"healthy", "normal", "control"}).sum())
    dataset.n_cancer = int(metadata["disease_state"].str.casefold().isin({"cancer", "tumor", "tumour"}).sum())
    dataset.is_validated = True
    dataset.validation_errors = None
    dataset.validation_warnings = {
        "excluded_gene_ids": int(qc_result["summary"]["invalid_gene_ids"]),
        "duplicate_gene_ids_aggregated": int(qc_result["summary"]["duplicate_gene_ids_aggregated"]),
    }
    dataset.source_version = version
    dataset.retrieval_url = retrieval_url
    dataset.download_date = download_date
    dataset.checksum = checksum
    dataset.status = "AVAILABLE"
    dataset.processing_steps = json_safe(processing_steps)
    dataset.provenance = json_safe({
        **provenance,
        "raw_expression_path": raw_expression_path,
        "processed_expression_path": expression_path,
        "metadata_path": metadata_path,
    })

    run_link = session.execute(
        select(AnalysisRunDataset).where(
            AnalysisRunDataset.run_id == run.id,
            AnalysisRunDataset.dataset_id == dataset.id,
        )
    ).scalar_one_or_none()
    if run_link is None:
        run_link = AnalysisRunDataset(run_id=run.id, dataset_id=dataset.id, provenance=json_safe(provenance))
        session.add(run_link)

    metadata_by_id = metadata.set_index("sample_id")
    qc_by_id = qc_result["sample_qc"].set_index("sample_id")
    cluster_by_id = qc_result["sample_clustering"].set_index("sample_id")["cluster"].to_dict()
    for sample_id, sample_row in metadata_by_id.iterrows():
        raw_state = str(sample_row.get("disease_state", "")).strip().casefold()
        if raw_state in {"healthy", "normal", "control", "solid tissue normal"}:
            disease_state = DiseaseStateEnum.HEALTHY
        elif any(term in raw_state for term in ("cancer", "tumor", "tumour", "carcinoma", "disease")):
            disease_state = DiseaseStateEnum.CANCER
        else:
            raise ValueError(f"Sample {sample_id} has an unrecognized disease state: {raw_state!r}")

        sample = session.execute(
            select(Sample).where(Sample.dataset_id == dataset.id, Sample.sample_id == str(sample_id))
        ).scalar_one_or_none()
        if sample is None:
            sample = Sample(dataset_id=dataset.id, sample_id=str(sample_id), disease_state=disease_state)
            session.add(sample)
        sample.disease_state = disease_state
        sample.stage = next((str(sample_row[key]) for key in ("ajcc_pathologic_stage", "stage") if key in sample_row and pd.notna(sample_row[key]) and str(sample_row[key]).strip()), None)
        sample.batch = next((str(sample_row[key]) for key in ("batch", "plate", "center", "processing_batch") if key in sample_row and pd.notna(sample_row[key]) and str(sample_row[key]).strip()), None)
        age = sample_row.get("age_at_index_years", sample_row.get("age"))
        try:
            sample.age = float(age) if age not in (None, "") and pd.notna(age) else None
        except (TypeError, ValueError):
            sample.age = None
        sample.sex = str(sample_row["sex_at_birth"])[:10] if sample_row.get("sex_at_birth") else None
        sample.extra_metadata = json_safe(sample_row.to_dict())

        qc_row = qc_by_id.loc[str(sample_id)]
        session.add(SampleQC(
            run_id=run.id,
            dataset_id=dataset.id,
            sample_id=str(sample_id),
            library_size=json_safe(qc_row.get("library_size")),
            detected_genes=json_safe(qc_row.get("detected_genes")),
            missing_fraction=json_safe(qc_row.get("missing_fraction")),
            zero_fraction=json_safe(qc_row.get("zero_fraction")),
            mean_expression=json_safe(qc_row.get("mean_expression")),
            median_expression=json_safe(qc_row.get("median_expression")),
            outlier_score=json_safe(qc_row.get("outlier_score")),
            is_outlier=bool(qc_row.get("is_outlier", False)),
            excluded=bool(qc_row.get("excluded", False)),
            exclusion_reason=qc_row.get("exclusion_reason"),
            pca_coordinates=json_safe(qc_row.get("pca_coordinates", {})),
            cluster=int(cluster_by_id[sample_id]) if sample_id in cluster_by_id else None,
            batch_metadata=json_safe(qc_row.get("batch_metadata", {})),
            sample_metadata=json_safe(sample_row.to_dict()),
        ))
    session.flush()
    return dataset