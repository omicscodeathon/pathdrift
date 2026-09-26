"""
Dataset management routes: upload, validate, list, delete.
Handles secure file upload with validation before analysis.
"""
import os
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, Dataset, Sample, SpeciesEnum, DataTypeEnum
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


@router.delete("/{dataset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dataset(
    dataset_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    svc = DatasetService(db, current_user, settings)
    await svc.delete_dataset(dataset_id)
