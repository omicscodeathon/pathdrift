"""Drift analysis routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, DriftAnalysis, BackgroundJob, GeneNetwork, JobStatusEnum
from app.schemas.schemas import DriftConfig, DriftResultOut, JobOut

router = APIRouter()


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def run_drift(
    config: DriftConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate both networks exist and are complete
    for net_id in [config.healthy_network_id, config.disease_network_id]:
        r = await db.execute(select(GeneNetwork).where(GeneNetwork.id == net_id))
        net = r.scalar_one_or_none()
        if not net:
            raise HTTPException(status_code=404, detail=f"Network {net_id} not found")
        if net.status != JobStatusEnum.COMPLETED:
            raise HTTPException(
                status_code=400,
                detail=f"Network {net_id} is not in COMPLETED state (current: {net.status})",
            )

    drift = DriftAnalysis(
        analysis_id=config.analysis_id,
        healthy_network_id=config.healthy_network_id,
        disease_network_id=config.disease_network_id,
        species=config.species,
    )
    db.add(drift)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_drift_detection")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.analysis_tasks import run_drift_detection
    task = run_drift_detection.apply_async(args=[bg_job.id, drift.id], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = drift.id
    await db.flush()
    return bg_job


@router.get("/{drift_id}", response_model=DriftResultOut)
async def get_drift_result(
    drift_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DriftAnalysis).where(DriftAnalysis.id == drift_id))
    drift = result.scalar_one_or_none()
    if not drift:
        raise HTTPException(status_code=404, detail="Drift analysis not found")
    return drift


@router.get("/{drift_id}/nodes")
async def get_node_drift(
    drift_id: str,
    limit: int = 500,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DriftAnalysis).where(DriftAnalysis.id == drift_id))
    drift = result.scalar_one_or_none()
    if not drift or not drift.node_drift_file_path:
        raise HTTPException(status_code=404, detail="Node drift results not available")
    df = pd.read_parquet(drift.node_drift_file_path)
    return df.nlargest(limit, "node_drift_score").to_dict(orient="records")


@router.get("/{drift_id}/edges")
async def get_edge_drift(
    drift_id: str,
    edge_type: str = None,
    limit: int = 1000,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(DriftAnalysis).where(DriftAnalysis.id == drift_id))
    drift = result.scalar_one_or_none()
    if not drift or not drift.edge_drift_file_path:
        raise HTTPException(status_code=404, detail="Edge drift results not available")
    df = pd.read_parquet(drift.edge_drift_file_path)
    if edge_type:
        df = df[df["type"] == edge_type]
    return df.head(limit).to_dict(orient="records")
