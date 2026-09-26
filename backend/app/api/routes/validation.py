"""
Validation routes: independent external validation of ML models.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, MLExperiment, ModelMetric, JobStatusEnum
from app.schemas.schemas import ModelMetricOut

router = APIRouter()


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
