"""ML experiment routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, MLExperiment, ModelMetric, BackgroundJob, Analysis
from app.schemas.schemas import MLExperimentConfig, MLExperimentOut, ModelMetricOut, JobOut

router = APIRouter()


@router.post("/experiments", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def create_ml_experiment(
    config: MLExperimentConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Analysis).where(Analysis.id == config.analysis_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Analysis not found")

    exp = MLExperiment(
        analysis_id=config.analysis_id,
        name=config.name,
        experiment_type=config.experiment_type,
        model_type=config.model_type,
        training_dataset_id=config.training_dataset_id,
        validation_dataset_id=config.validation_dataset_id,
        random_seed=config.random_seed,
        cv_folds=config.cv_folds,
        test_size=config.test_size,
        hyperparams=config.hyperparams,
        feature_selection_config=config.feature_selection_config,
        class_weight=config.class_weight,
    )
    # Store optional drift/cross-species references
    if config.drift_analysis_id:
        exp.drift_analysis_id = config.drift_analysis_id
    if config.cross_species_analysis_id:
        exp.cross_species_analysis_id = config.cross_species_analysis_id
    if config.preprocessing_job_id:
        exp.preprocessing_job_id = config.preprocessing_job_id

    db.add(exp)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_ml_experiment")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.ml_tasks import run_ml_experiment
    task = run_ml_experiment.apply_async(args=[bg_job.id, exp.id], queue="ml")
    bg_job.celery_task_id = task.id
    await db.flush()
    return bg_job


@router.get("/experiments/{exp_id}", response_model=MLExperimentOut)
async def get_experiment(
    exp_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MLExperiment).where(MLExperiment.id == exp_id))
    exp = result.scalar_one_or_none()
    if not exp:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return exp


@router.get("/experiments/{exp_id}/metrics", response_model=list[ModelMetricOut])
async def get_metrics(
    exp_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ModelMetric).where(ModelMetric.experiment_id == exp_id))
    return result.scalars().all()


@router.get("/experiments/{exp_id}/feature-importances")
async def get_feature_importances(
    exp_id: str,
    limit: int = 100,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(MLExperiment).where(MLExperiment.id == exp_id))
    exp = result.scalar_one_or_none()
    if not exp or not exp.feature_importance_path:
        raise HTTPException(status_code=404, detail="Feature importances not available")
    df = pd.read_parquet(exp.feature_importance_path)
    return df.head(limit).to_dict(orient="records")
