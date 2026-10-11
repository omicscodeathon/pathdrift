"""
Dataset management routes: upload, validate, list, delete.
Handles secure file upload with validation before analysis.
"""
import asyncio
import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import numpy as np
import pandas as pd
from sklearn.decomposition import PCA

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import Analysis, User, Dataset, PreprocessingJob, Sample, SpeciesEnum, DataTypeEnum, JobStatusEnum
from app.schemas.schemas import DatasetCreate, DatasetOut, DatasetValidationResult, SampleOut
from app.core.config import settings
from app.services.dataset_service import DatasetService

router = APIRouter()


@router.post("/upload", response_model=DatasetOut, status_code=status.HTTP_201_CREATED)
async def upload_dataset(
    project_id: str = Form(...),
    name: str = Form(...),
    species: SpeciesEnum = Form(...),
    data_type: DataTypeEnum = Form(...),
    tissue: Optional[str] = Form(None),
    source: Optional[str] = Form(None),
    accession: Optional[str] = Form(None),
    platform: Optional[str] = Form(None),
    description: Optional[str] = Form(None),
    expression_file: UploadFile = File(...),
    metadata_file: Optional[UploadFile] = File(None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    dataset = await svc.create_dataset(
        project_id=project_id,
        name=name,
        species=species,
        data_type=data_type,
        tissue=tissue,
        source=source,
        accession=accession,
        platform=platform,
        description=description,
        expression_file=expression_file,
        metadata_file=metadata_file,
    )
    return dataset


@router.get("/{dataset_id}", response_model=DatasetOut)
async def get_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    return await svc.get_dataset(dataset_id)


@router.get("/project/{project_id}", response_model=list[DatasetOut])
async def list_datasets(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    return await svc.list_datasets(project_id)


@router.post("/{dataset_id}/validate", response_model=DatasetValidationResult)
async def validate_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    return await svc.validate_dataset(dataset_id)


@router.get("/{dataset_id}/samples", response_model=list[SampleOut])
async def get_samples(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    await svc.get_dataset(dataset_id)  # permission check
    result = await db.execute(select(Sample).where(Sample.dataset_id == dataset_id))
    return result.scalars().all()


@router.get("/{dataset_id}/quality")
async def get_dataset_quality(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    dataset = await svc.get_dataset(dataset_id)
    if not dataset.expression_file_path or not os.path.isfile(dataset.expression_file_path):
        raise HTTPException(status_code=404, detail="Dataset expression matrix not found")

    preprocessing_result = await db.execute(
        select(PreprocessingJob)
        .join(Analysis, Analysis.id == PreprocessingJob.analysis_id)
        .where(
            PreprocessingJob.dataset_id == dataset_id,
            PreprocessingJob.status == JobStatusEnum.COMPLETED,
            Analysis.project_id == dataset.project_id,
            Analysis.project.has(owner_id=current_user.id),
        )
        .order_by(PreprocessingJob.created_at.desc())
        .limit(1)
    )
    preprocessing_job = preprocessing_result.scalar_one_or_none()
    processed_path = (
        preprocessing_job.output_file_path
        if preprocessing_job and preprocessing_job.output_file_path and os.path.isfile(preprocessing_job.output_file_path)
        else None
    )

    try:
        return await asyncio.to_thread(
            _build_dataset_quality,
            dataset_id,
            dataset.expression_file_path,
            dataset.metadata_file_path,
            processed_path,
            dataset.data_type,
            preprocessing_job,
        )
    except (OSError, ValueError, pd.errors.ParserError) as error:
        raise HTTPException(status_code=422, detail=f"Could not calculate sample QC: {error}") from error


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    await svc.delete_dataset(dataset_id)


def _read_quality_matrix(path: str) -> pd.DataFrame:
    if path.endswith(".parquet"):
        return pd.read_parquet(path)
    return DatasetService._load_expression_matrix(path)


def _build_dataset_quality(
    dataset_id: str,
    expression_path: str,
    metadata_path: Optional[str],
    processed_path: Optional[str],
    data_type: DataTypeEnum,
    preprocessing_job: Optional[PreprocessingJob],
) -> dict:
    raw_matrix = _read_quality_matrix(expression_path)
    analysis_matrix = _read_quality_matrix(processed_path) if processed_path else raw_matrix

    metadata = None
    if metadata_path and os.path.isfile(metadata_path):
        compression = "gzip" if metadata_path.endswith(".gz") else None
        separator = "\t" if metadata_path.endswith((".tsv", ".txt", ".tsv.gz", ".txt.gz")) else ","
        try:
            metadata = pd.read_csv(metadata_path, sep=separator, compression=compression)
            metadata.columns = metadata.columns.str.lower()
        except (OSError, pd.errors.ParserError, UnicodeDecodeError):
            metadata = None

    sample_labels = {}
    if metadata is not None and {"sample_id", "disease_state"}.issubset(metadata.columns):
        sample_labels = dict(zip(
            metadata["sample_id"].astype(str),
            metadata["disease_state"].fillna("Unlabeled").astype(str),
        ))

    numeric_matrix = analysis_matrix.apply(lambda column: pd.to_numeric(column, errors="coerce"))
    numeric_matrix = numeric_matrix.replace([np.inf, -np.inf], np.nan)
    numeric_matrix = numeric_matrix.dropna(axis=0, how="all").dropna(axis=1, how="all")
    numeric_matrix = numeric_matrix.fillna(numeric_matrix.median(axis=1), axis=0).fillna(0)
    if data_type == DataTypeEnum.RAW_COUNTS and (numeric_matrix >= 0).all().all():
        numeric_matrix = np.log2(numeric_matrix + 1)

    variances = numeric_matrix.var(axis=1)
    variable_genes = variances[variances > 0].nlargest(2000).index
    pca_matrix = numeric_matrix.loc[variable_genes].transpose().to_numpy(dtype=np.float64)
    pca_points = []
    explained_variance = []
    pca_message = None
    if pca_matrix.shape[0] < 2 or pca_matrix.shape[1] < 2:
        pca_message = "PCA requires at least two samples and two variable genes."
    else:
        model = PCA(n_components=2, random_state=42)
        transformed = model.fit_transform(pca_matrix)
        explained_variance = model.explained_variance_ratio_.tolist()
        pca_points = [
            {
                "sample_id": str(sample_id),
                "group": sample_labels.get(str(sample_id), "Unlabeled"),
                "pc1": float(point[0]),
                "pc2": float(point[1]),
            }
            for sample_id, point in zip(numeric_matrix.columns, transformed)
        ]

    return {
        "dataset_id": dataset_id,
        "before_sample_count": int(raw_matrix.shape[1]),
        "after_sample_count": int(analysis_matrix.shape[1]) if processed_path else None,
        "preprocessing_status": "completed" if processed_path else None,
        "pca_source": "preprocessed" if processed_path else "raw",
        "pca_gene_count": int(pca_matrix.shape[1]),
        "pca_points": pca_points,
        "explained_variance_ratio": explained_variance,
        "pca_message": pca_message,
        "outlier_samples": (preprocessing_job.outlier_samples or []) if preprocessing_job and processed_path else [],
    }
