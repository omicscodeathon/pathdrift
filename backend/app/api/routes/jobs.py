"""Background job management routes."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, BackgroundJob, Analysis, JobStatusEnum
from app.schemas.schemas import JobOut

router = APIRouter()


@router.get("/{job_id}", response_model=JobOut)
async def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.get("/analysis/{analysis_id}", response_model=list[JobOut])
async def get_jobs_for_analysis(
    analysis_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BackgroundJob)
        .where(BackgroundJob.analysis_id == analysis_id)
        .order_by(BackgroundJob.created_at.desc())
    )
    return result.scalars().all()


@router.post("/{job_id}/cancel")
async def cancel_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(BackgroundJob).where(BackgroundJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.celery_task_id:
        from app.tasks.celery_app import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    job.status = JobStatusEnum.CANCELLED
    await db.flush()
    return {"status": "cancelled"}
