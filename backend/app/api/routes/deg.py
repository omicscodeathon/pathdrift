"""DEG analysis routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd
from typing import Optional

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, DEGResult, BackgroundJob, Analysis, Dataset, JobStatusEnum
from app.schemas.schemas import DEGConfig, DEGResultOut, JobOut

router = APIRouter()


@router.get("/latest/analysis/{analysis_id}", response_model=Optional[DEGResultOut])
async def get_latest_deg_result(
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
        select(DEGResult)
        .where(DEGResult.analysis_id == analysis_id)
        .order_by(DEGResult.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


@router.get("/latest/analysis/{analysis_id}/genes")
async def get_latest_deg_genes(
    analysis_id: str,
    significant_only: bool = True,
    limit: int = 500,
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
        select(DEGResult)
        .where(DEGResult.analysis_id == analysis_id)
        .order_by(DEGResult.created_at.desc())
        .limit(1)
    )
    deg = result.scalar_one_or_none()
    if not deg or deg.status != JobStatusEnum.COMPLETED or not deg.results_file_path:
        return []

    df = pd.read_parquet(deg.results_file_path)
    if significant_only:
        df = df[df["significant"]]
    return df.head(limit).reset_index().to_dict(orient="records")


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def run_deg(
    config: DEGConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    analysis_result = await db.execute(
        select(Analysis).where(
            Analysis.id == config.analysis_id,
            Analysis.project.has(owner_id=current_user.id),
        )
    )
    analysis = analysis_result.scalar_one_or_none()
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

    deg_result = DEGResult(
        analysis_id=config.analysis_id,
        dataset_id=config.dataset_id,
        preprocessing_job_id=config.preprocessing_job_id,
        method=config.method,
        fdr_threshold=config.fdr_threshold,
        lfc_threshold=config.lfc_threshold,
    )
    db.add(deg_result)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_deg")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.analysis_tasks import run_deg as run_deg_task
    task = run_deg_task.apply_async(args=[bg_job.id, deg_result.id], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = deg_result.id
    await db.flush()
    return bg_job


@router.get("/{deg_id}", response_model=DEGResultOut)
async def get_deg_result(
    deg_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DEGResult).where(DEGResult.id == deg_id))
    deg = result.scalar_one_or_none()
    if not deg:
        raise HTTPException(status_code=404, detail="DEG result not found")
    return deg


@router.get("/{deg_id}/genes")
async def get_deg_genes(
    deg_id: str,
    significant_only: bool = True,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DEGResult).where(DEGResult.id == deg_id))
    deg = result.scalar_one_or_none()
    if not deg or not deg.results_file_path:
        raise HTTPException(status_code=404, detail="DEG results not available")
    df = pd.read_parquet(deg.results_file_path)
    if significant_only:
        df = df[df["significant"]]
    return df.head(limit).reset_index().to_dict(orient="records")
