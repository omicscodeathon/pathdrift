"""Pathway analysis routes."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import User, PathwayResult, BackgroundJob, DriftAnalysis, DEGResult, JobStatusEnum
from app.schemas.schemas import PathwayConfig, PathwayResultOut, JobOut

router = APIRouter()


@router.post("/", response_model=JobOut, status_code=status.HTTP_202_ACCEPTED)
async def run_pathway_analysis(
    config: PathwayConfig,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Load gene list from drift or DEG source
    gene_list = []
    background_genes = []

    if config.source == "drift":
        r = await db.execute(select(DriftAnalysis).where(DriftAnalysis.id == config.source_id))
        drift = r.scalar_one_or_none()
        if not drift or not drift.node_drift_file_path:
            raise HTTPException(status_code=404, detail="Drift results not available")
        df = pd.read_parquet(drift.node_drift_file_path)
        drifting = df[df["node_drift_score"] >= 0.3]
        gene_list = drifting["gene_id"].tolist() if "gene_id" in drifting.columns else drifting.index.tolist()
        background_genes = df["gene_id"].tolist() if "gene_id" in df.columns else df.index.tolist()

    elif config.source == "deg":
        r = await db.execute(select(DEGResult).where(DEGResult.id == config.source_id))
        deg = r.scalar_one_or_none()
        if not deg or not deg.results_file_path:
            raise HTTPException(status_code=404, detail="DEG results not available")
        df = pd.read_parquet(deg.results_file_path)
        sig_genes = df[df["significant"]]
        gene_list = sig_genes.index.tolist()
        background_genes = df.index.tolist()

    if not gene_list:
        raise HTTPException(status_code=400, detail="No genes available for pathway analysis")

    pw = PathwayResult(
        analysis_id=config.analysis_id,
        gene_set=config.gene_set,
        source=config.source,
        species=config.species,
        fdr_threshold=config.fdr_threshold,
    )
    db.add(pw)
    await db.flush()

    bg_job = BackgroundJob(analysis_id=config.analysis_id, task_name="run_pathway_analysis")
    db.add(bg_job)
    await db.flush()
    await db.refresh(bg_job)

    from app.tasks.analysis_tasks import run_pathway_analysis as run_pw_task
    task = run_pw_task.apply_async(args=[bg_job.id, pw.id, gene_list, background_genes], queue="analysis")
    bg_job.celery_task_id = task.id
    bg_job.result_ref = pw.id
    await db.flush()
    return bg_job


@router.get("/{pw_id}", response_model=PathwayResultOut)
async def get_pathway_result(
    pw_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PathwayResult).where(PathwayResult.id == pw_id))
    pw = result.scalar_one_or_none()
    if not pw:
        raise HTTPException(status_code=404, detail="Pathway result not found")
    return pw


@router.get("/{pw_id}/terms")
async def get_pathway_terms(
    pw_id: str,
    significant_only: bool = True,
    limit: int = 50,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(PathwayResult).where(PathwayResult.id == pw_id))
    pw = result.scalar_one_or_none()
    if not pw or not pw.results_file_path:
        raise HTTPException(status_code=404, detail="Results not available")
    df = pd.read_parquet(pw.results_file_path)
    if significant_only and "significant" in df.columns:
        df = df[df["significant"]]
    return df.head(limit).to_dict(orient="records")
