"""Drift analysis routes."""
import asyncio
import os

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import numpy as np
import pandas as pd

from app.db.base import get_db
from app.api.deps import get_current_user
from app.models import Analysis, Project, User, DriftAnalysis, BackgroundJob, GeneNetwork, JobStatusEnum, OrthologyMapping, SpeciesEnum
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


@router.get("/project/{project_id}", response_model=list[DriftResultOut])
async def list_project_drift_results(
    project_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    project_result = await db.execute(
        select(Project).where(Project.id == project_id, Project.owner_id == current_user.id)
    )
    if not project_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Project not found")
    result = await db.execute(
        select(DriftAnalysis)
        .join(Analysis, Analysis.id == DriftAnalysis.analysis_id)
        .where(Analysis.project_id == project_id)
        .order_by(DriftAnalysis.created_at.desc())
    )
    return result.scalars().all()


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


@router.get("/{drift_id}/summary")
async def get_drift_summary(
    drift_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(DriftAnalysis)
        .join(Analysis, Analysis.id == DriftAnalysis.analysis_id)
        .where(
            DriftAnalysis.id == drift_id,
            Analysis.project.has(owner_id=current_user.id),
        )
    )
    drift = result.scalar_one_or_none()
    if not drift:
        raise HTTPException(status_code=404, detail="Drift analysis not found")
    if drift.status != JobStatusEnum.COMPLETED or not drift.node_drift_file_path:
        raise HTTPException(status_code=409, detail="Completed node drift results are not available")
    if not os.path.isfile(drift.node_drift_file_path):
        raise HTTPException(status_code=404, detail="Node drift file not found")

    try:
        node_frame = await asyncio.to_thread(pd.read_parquet, drift.node_drift_file_path)
    except (OSError, ValueError, ImportError) as error:
        raise HTTPException(status_code=422, detail="Unable to read node drift results") from error
    if not {"gene_id", "node_drift_score"}.issubset(node_frame.columns):
        raise HTTPException(status_code=422, detail="Node drift result has an unexpected structure")

    node_frame = node_frame.copy()
    node_frame["node_drift_score"] = pd.to_numeric(node_frame["node_drift_score"], errors="coerce")
    valid_scores = node_frame.dropna(subset=["node_drift_score"])
    scores = valid_scores["node_drift_score"].to_numpy(dtype=float)
    max_score = max(1.0, float(scores.max())) if scores.size else 1.0
    bin_edges = np.linspace(0.0, max_score, 11)
    counts, bin_edges = np.histogram(scores, bins=bin_edges)
    distribution = [
        {"low": float(bin_edges[index]), "high": float(bin_edges[index + 1]), "count": int(counts[index])}
        for index in range(len(counts))
    ]

    top_nodes = valid_scores.nlargest(50, "node_drift_score").copy()
    module_result = await db.execute(select(GeneNetwork).where(GeneNetwork.id == drift.disease_network_id))
    disease_network = module_result.scalar_one_or_none()
    module_by_gene = {}
    if disease_network and disease_network.node_features_file_path and os.path.isfile(disease_network.node_features_file_path):
        try:
            features = await asyncio.to_thread(pd.read_parquet, disease_network.node_features_file_path)
            if {"gene_id", "module"}.issubset(features.columns):
                module_by_gene = dict(zip(features["gene_id"].astype(str), features["module"].astype(str)))
        except (OSError, ValueError, ImportError):
            module_by_gene = {}

    top_gene_ids = top_nodes["gene_id"].dropna().astype(str).tolist()
    if drift.species == SpeciesEnum.HUMAN:
        symbol_query = select(OrthologyMapping.human_ensembl_id, OrthologyMapping.human_symbol).where(
            OrthologyMapping.human_ensembl_id.in_(top_gene_ids),
            OrthologyMapping.human_symbol.is_not(None),
        )
    else:
        symbol_query = select(OrthologyMapping.mouse_ensembl_id, OrthologyMapping.mouse_symbol).where(
            OrthologyMapping.mouse_ensembl_id.in_(top_gene_ids),
            OrthologyMapping.mouse_symbol.is_not(None),
        )
    symbol_result = await db.execute(symbol_query)
    symbol_by_gene = {str(gene_id): symbol for gene_id, symbol in symbol_result.all()}
    top_genes = []
    for _, row in top_nodes.iterrows():
        gene_id = str(row["gene_id"])
        top_genes.append({
            "gene_id": gene_id,
            "symbol": symbol_by_gene.get(gene_id),
            "drift_score": float(row["node_drift_score"]),
            "module": module_by_gene.get(gene_id),
            "degree_change": float(row["degree_change"]) if "degree_change" in row and pd.notna(row["degree_change"]) else None,
        })

    return {
        "drift_id": drift.id,
        "species": drift.species.value,
        "status": drift.status.value,
        "global_drift_score": drift.global_drift_score,
        "n_conserved_edges": drift.n_conserved_edges,
        "n_gained_edges": drift.n_gained_edges,
        "n_lost_edges": drift.n_lost_edges,
        "total_genes": int(len(valid_scores)),
        "distribution": distribution,
        "top_genes": top_genes,
    }


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
