"""
Validation routes: independent external validation of ML models.
"""
import asyncio
import json
import os

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import Analysis, BackgroundJob, DriftAnalysis, JobStatusEnum, MLExperiment, ModelMetric, Project, User
from app.schemas.schemas import JobOut, ModelMetricOut

router = APIRouter()


class ValidationRunRequest(BaseModel):
    drift_analysis_id: str
    permutations: int = Field(default=199, ge=19, le=999)
    random_seed: int = 42


@router.post("/runs", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_validation_run(
    payload: ValidationRunRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriftAnalysis)
        .join(Analysis, Analysis.id == DriftAnalysis.analysis_id)
        .join(Project, Project.id == Analysis.project_id)
        .where(DriftAnalysis.id == payload.drift_analysis_id, Project.owner_id == current_user.id)
    )
    drift = result.scalar_one_or_none()
    if not drift:
        raise HTTPException(status_code=404, detail="Drift analysis not found")
    if drift.status != JobStatusEnum.COMPLETED:
        raise HTTPException(status_code=409, detail="Complete the drift analysis before validation")

    job = BackgroundJob(analysis_id=drift.analysis_id, task_name="run_scientific_validation")
    db.add(job)
    await db.flush()
    await db.refresh(job)
    from app.tasks.validation_tasks import run_scientific_validation
    task = run_scientific_validation.apply_async(
        args=[job.id, drift.id, payload.permutations, payload.random_seed],
        queue="analysis",
    )
    job.celery_task_id = task.id
    await db.flush()
    return job


@router.get("/runs/{job_id}")
async def get_validation_run(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(BackgroundJob)
        .join(Analysis, Analysis.id == BackgroundJob.analysis_id)
        .join(Project, Project.id == Analysis.project_id)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.task_name == "run_scientific_validation",
            Project.owner_id == current_user.id,
        )
    )
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status_code=404, detail="Validation run not found")

    report = None
    if job.status == JobStatusEnum.COMPLETED:
        if not job.result_ref or not os.path.isfile(job.result_ref):
            raise HTTPException(status_code=500, detail="Saved validation report is unavailable")
        try:
            with open(job.result_ref, "r", encoding="utf-8") as result_file:
                report = await asyncio.to_thread(json.load, result_file)
        except (OSError, json.JSONDecodeError) as error:
            raise HTTPException(status_code=500, detail="Saved validation report could not be read") from error
    return {
        "id": job.id,
        "status": job.status.value,
        "progress": job.progress,
        "progress_message": job.progress_message,
        "error_message": job.error_message,
        "result": report,
    }


@router.get("/experiments/{exp_id}/comparison")
async def compare_models(
    exp_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Compare all three model types (expression, drift, combined)
    within the same analysis to answer the core research question.
    """
    result = await db.execute(select(MLExperiment).where(MLExperiment.id == exp_id))
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")

    # Get all experiments in the same analysis
    result = await db.execute(
        select(MLExperiment).where(MLExperiment.analysis_id == exp.analysis_id)
    )
    all_exps = result.scalars().all()

    comparison = []
    for e in all_exps:
        metrics_r = await db.execute(
            select(ModelMetric).where(ModelMetric.experiment_id == e.id)
        )
        metrics = metrics_r.scalars().all()
        comparison.append(
            {
                "experiment_id": e.id,
                "name": e.name,
                "experiment_type": e.experiment_type,
                "model_type": e.model_type,
                "status": e.status,
                "metrics": [m.__dict__ for m in metrics],
            }
        )

    return {
        "analysis_id": exp.analysis_id,
        "comparison": comparison,
        "research_question": (
            "Does network-drift improve early breast cancer state prediction "
            "beyond conventional gene expression features?"
        ),
    }
