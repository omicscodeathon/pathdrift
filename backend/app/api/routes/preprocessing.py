"""Preprocessing routes."""
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, PreprocessingJob, BackgroundJob, Analysis, Dataset, JobStatusEnum
from app.schemas.schemas import PreprocessingConfig, PreprocessingJobOut, JobOut

router = APIRouter()


@router.get("/latest/analysis/{analysis_id}", response_model=Optional[PreprocessingJobOut])
async def get_latest_preprocessing_job(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis_result = await db.execute(
        select(Analysis).where(
            Analysis.id == analysis_id,
            Analysis.project.has(owner_id=current_user.id),
        )
    )
    if not analysis_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Analysis not found")

    result = await db.execute(
        select(PreprocessingJob)
        .where(PreprocessingJob.analysis_id == analysis_id)
        .order_by(PreprocessingJob.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def start_preprocessing(
    config: PreprocessingConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Queue a preprocessing job. Returns the background job record."""
    # Verify analysis ownership
    result = await db.execute(select(Analysis).where(
        Analysis.id == config.analysis_id, Analysis.project.has(owner_id=current_user.id)
    ))
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    dataset_result = await db.execute(
        select(Dataset).where(
            Dataset.id == config.dataset_id,
            Dataset.owner_id == current_user.id,
        )
    )
    dataset = dataset_result.scalar_one_or_none()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset not found or access denied")
    if dataset.project_id != analysis.project_id:
        raise HTTPException(status_code=400, detail="Dataset does not belong to the selected analysis project")

    pp_job = PreprocessingJob(
        analysis_id=config.analysis_id,
        dataset_id=config.dataset_id,
        normalization_method=config.normalization_method,
        low_expr_threshold=config.low_expr_threshold,
        low_expr_min_samples=config.low_expr_min_samples,
        min_gene_variance=config.min_gene_variance,
        remove_duplicates=config.remove_duplicates,
        impute_missing=config.impute_missing,
        batch_correct=config.batch_correct,
        batch_correction_method=config.batch_correction_method,
        outlier_detection=config.outlier_detection,
    )
    db.add(pp_job)
    await db.flush()

    bg_job = BackgroundJob(
        analysis_id=config.analysis_id,
        task_name="run_preprocessing",
    )
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)
    await db.refresh(pp_job)

    # Dispatch Celery task
    from app.tasks.analysis_tasks import run_preprocessing
    task = run_preprocessing.apply_async(args=[bg_job.id, pp_job.id], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = pp_job.id
    await db.flush()

    return bg_job


@router.get("/{job_id}", response_model=PreprocessingJobOut)
async def get_preprocessing_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PreprocessingJob).where(PreprocessingJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Preprocessing job not found")
    return job
