"""Cross-species comparison routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, CrossSpeciesAnalysis, DriftAnalysis, BackgroundJob, JobStatusEnum
from app.schemas.schemas import CrossSpeciesConfig, CrossSpeciesOut, JobOut

router = APIRouter()


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def run_cross_species(
    config: CrossSpeciesConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    for drift_id in [config.human_drift_id, config.mouse_drift_id]:
        r = await db.execute(select(DriftAnalysis).where(DriftAnalysis.id == drift_id))
        drift = r.scalar_one_or_none()
        if not drift:
            raise HTTPException(status_code=404, detail=f"Drift analysis {drift_id} not found")
        if drift.status != JobStatusEnum.COMPLETED:
            raise HTTPException(status_code=400, detail=f"Drift analysis {drift_id} not completed")

    cs = CrossSpeciesAnalysis(
        analysis_id=config.analysis_id,
        human_drift_id=config.human_drift_id,
        mouse_drift_id=config.mouse_drift_id,
    )
    db.add(cs)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_cross_species")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.analysis_tasks import run_cross_species as run_cs_task
    task = run_cs_task.apply_async(args=[bg_job.id, cs.id], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = cs.id
    await db.flush()
    return bg_job


@router.get("/{cs_id}", response_model=CrossSpeciesOut)
async def get_cross_species(
    cs_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CrossSpeciesAnalysis).where(CrossSpeciesAnalysis.id == cs_id))
    cs = result.scalar_one_or_none()
    if not cs:
        raise HTTPException(status_code=404, detail="Cross-species analysis not found")
    return cs


@router.get("/{cs_id}/genes")
async def get_conserved_genes(
    cs_id: str,
    classification: str = None,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CrossSpeciesAnalysis).where(CrossSpeciesAnalysis.id == cs_id))
    cs = result.scalar_one_or_none()
    if not cs or not cs.comparison_file_path:
        raise HTTPException(status_code=404, detail="Results not available")
    df = pd.read_parquet(cs.comparison_file_path)
    if classification:
        df = df[df["drift_classification"] == classification]
    return df.head(limit).to_dict(orient="records")
